import numpy as np
import pandas as pd
import torch
import torch.nn as nn
from torch.utils.data import DataLoader, TensorDataset
from scipy.integrate import solve_ivp
import matplotlib.pyplot as plt
from sklearn.preprocessing import StandardScaler
from sklearn.model_selection import train_test_split
import warnings
import time
import os

warnings.filterwarnings("ignore")

CSV_PATH = "data/synthetic_alcohol_population_v2.csv"
MODEL_SAVE_PATH = "model/pinn_alcohol_model.pt"
EPOCHS = 300
BATCH_SIZE = 512
LR = 1e-3
PHYSICS_W = 0.5
PARAM_W = 1.0
RANDOM_SEED = 42

DEVICE = torch.device("cuda" if torch.cuda.is_available() else "cpu")
torch.manual_seed(RANDOM_SEED)
np.random.seed(RANDOM_SEED)

INPUT_COLS = [
    "weight", "height", "age", "gender_code",
    "alcohol_dose_g", "drinking_duration",
    "meal_calories", "meal_fat_g",
    "TBW", "LBM",
]
PARAM_COLS = ["Vmax", "Km", "kBBB", "kg", "ka"]
TARGET_COLS = [
    "peak_BAC_pct", "peak_BrAC_pct", "recovery_time_hr",
    "P_mild_pct", "P_moderate_pct", "P_severe_pct",
    "P_blackout_pct", "P_passout_pct",
]
DRINK_COLS = ["alcohol_dose_g", "drinking_duration", "TBW"]


class PINN(nn.Module):
    def __init__(self, n_in, n_params, n_out):
        super().__init__()
        self.trunk = nn.Sequential(
            nn.Linear(n_in, 256), nn.LayerNorm(256), nn.SiLU(), nn.Dropout(0.10),
            nn.Linear(256, 256), nn.LayerNorm(256), nn.SiLU(), nn.Dropout(0.10),
            nn.Linear(256, 128), nn.LayerNorm(128), nn.SiLU(), nn.Dropout(0.05),
            nn.Linear(128, 64), nn.SiLU(),
        )
        self.param_head = nn.Sequential(
            nn.Linear(64, 128), nn.SiLU(),
            nn.Linear(128, 64), nn.SiLU(),
            nn.Linear(64, 32), nn.SiLU(),
            nn.Linear(32, n_params),
        )
        self.output_head = nn.Sequential(
            nn.Linear(n_params, 128), nn.SiLU(),
            nn.Linear(128, 128), nn.SiLU(),
            nn.Linear(128, 64), nn.SiLU(),
            nn.Linear(64, 32), nn.SiLU(),
            nn.Linear(32, n_out),
        )

    def forward(self, x):
        feat = self.trunk(x)
        p_est = self.param_head(feat)
        out = self.output_head(p_est)
        return p_est, out


def load_data(csv_path):
    df = pd.read_csv(csv_path)
    df["gender_code"] = (df["gender"] == "male").astype(float)
    return df


def build_loaders(df, batch_size, seed):
    X_raw = df[INPUT_COLS].values.astype(np.float32)
    P_raw = df[PARAM_COLS].values.astype(np.float32)
    Y_raw = df[TARGET_COLS].values.astype(np.float32)
    D_raw = df[DRINK_COLS].values.astype(np.float32)

    scaler_X = StandardScaler()
    scaler_Y = StandardScaler()
    scaler_P = StandardScaler()

    X_sc = scaler_X.fit_transform(X_raw).astype(np.float32)
    Y_sc = scaler_Y.fit_transform(Y_raw).astype(np.float32)
    P_sc = scaler_P.fit_transform(P_raw).astype(np.float32)

    idx = np.arange(len(X_sc))
    tr_idx, va_idx = train_test_split(idx, test_size=0.15, random_state=seed)

    def to_t(arr):
        return torch.tensor(arr, dtype=torch.float32).to(DEVICE)

    X_tr, X_va = to_t(X_sc[tr_idx]), to_t(X_sc[va_idx])
    Y_tr, Y_va = to_t(Y_sc[tr_idx]), to_t(Y_sc[va_idx])
    P_tr, P_va = to_t(P_sc[tr_idx]), to_t(P_sc[va_idx])
    D_tr, D_va = to_t(D_raw[tr_idx]), to_t(D_raw[va_idx])

    train_loader = DataLoader(TensorDataset(X_tr, Y_tr, P_tr, D_tr),
                              batch_size=batch_size, shuffle=True)
    val_loader = DataLoader(TensorDataset(X_va, Y_va, P_va, D_va),
                            batch_size=batch_size, shuffle=False)

    return (train_loader, val_loader,
            scaler_X, scaler_Y, scaler_P,
            X_sc, Y_raw, P_raw, tr_idx, va_idx)


def build_physics_loss_fn(scaler_P):
    P_mean = torch.tensor(scaler_P.mean_, dtype=torch.float32).to(DEVICE)
    P_std = torch.tensor(scaler_P.scale_, dtype=torch.float32).to(DEVICE)

    def fn(p_sc, drink_info):
        p = p_sc * P_std + P_mean
        Vmax = p[:, 0].clamp(0.5, 20.0)
        Km = p[:, 1].clamp(0.01, 5.0)
        ka = p[:, 4].clamp(0.10, 5.0)
        dose = drink_info[:, 0]
        dur = drink_info[:, 1].clamp(0.25, 4.0)

        B_peak = 0.60 * dose
        I_peak = 0.20 * dose
        residual_peak = ka * I_peak - (Vmax * B_peak) / (Km + B_peak)

        B_low = 0.05 * dose
        rm_low = (Vmax * B_low) / (Km + B_low)
        expected_low = (Vmax / Km) * B_low * 0.90
        residual_low = rm_low - expected_low

        min_vmax = 0.08 * dose / dur
        vmax_pen = torch.relu(min_vmax - Vmax)

        return (torch.mean(residual_peak ** 2)
                + 0.5 * torch.mean(residual_low ** 2)
                + 0.3 * torch.mean(vmax_pen ** 2))

    return fn


def train(model, train_loader, val_loader, physics_loss_fn, epochs, lr):
    optimiser = torch.optim.Adam(model.parameters(), lr=lr, weight_decay=1e-5)
    scheduler = torch.optim.lr_scheduler.ReduceLROnPlateau(
        optimiser, mode="min", patience=15, factor=0.5, min_lr=1e-5)
    mse = nn.MSELoss()
    history = {k: [] for k in
               ["train_total", "train_data", "train_params", "train_phys", "val_total"]}
    best_val = np.inf
    best_state = None
    t0 = time.time()

    for epoch in range(1, epochs + 1):
        model.train()
        run = dict(total=0., data=0., params=0., phys=0.)

        for xb, yb, pb, db in train_loader:
            optimiser.zero_grad()
            p_pred, y_pred = model(xb)
            l_data = mse(y_pred, yb)
            l_params = mse(p_pred, pb)
            l_phys = physics_loss_fn(p_pred, db)
            loss = l_data + PARAM_W * l_params + PHYSICS_W * l_phys
            loss.backward()
            nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            optimiser.step()
            run["total"] += loss.item()
            run["data"] += l_data.item()
            run["params"] += l_params.item()
            run["phys"] += l_phys.item()

        nb = len(train_loader)
        for k in run:
            run[k] /= nb

        model.eval()
        val_loss = 0.0
        with torch.no_grad():
            for xb, yb, pb, db in val_loader:
                _, y_pred = model(xb)
                val_loss += mse(y_pred, yb).item()
        val_loss /= len(val_loader)
        scheduler.step(val_loss)

        for k in ["total", "data", "params", "phys"]:
            history[f"train_{k}"].append(run[k])
        history["val_total"].append(val_loss)

        if val_loss < best_val:
            best_val = val_loss
            best_state = {k: v.cpu().clone() for k, v in model.state_dict().items()}

        if epoch % 25 == 0 or epoch == 1:
            print(f"Ep {epoch:>3}/{epochs}  "
                  f"train={run['total']:.4f}  "
                  f"dat={run['data']:.4f}  "
                  f"par={run['params']:.4f}  "
                  f"phy={run['phys']:.4f}  "
                  f"val={val_loss:.4f}  "
                  f"{(time.time()-t0)/60:.1f}min"
                  + ("  ★" if val_loss == best_val else ""))

    return best_state, best_val, history


def evaluate(model, X_sc, Y_raw, P_raw, va_idx, scaler_Y, scaler_P):
    model.eval()
    x_va = torch.tensor(X_sc[va_idx], dtype=torch.float32).to(DEVICE)
    with torch.no_grad():
        P_pred_sc, Y_pred_sc = model(x_va)

    Y_pred = scaler_Y.inverse_transform(Y_pred_sc.cpu().numpy())
    Y_true = Y_raw[va_idx]
    P_pred = scaler_P.inverse_transform(P_pred_sc.cpu().numpy())
    P_true = P_raw[va_idx]

    print("\n===== OUTPUT METRICS =====")
    print(f"  {'Target':<24} {'MAE':>8} {'RMSE':>8} {'R²':>8}")
    for i, col in enumerate(TARGET_COLS):
        yt, yp = Y_true[:, i], Y_pred[:, i]
        mae = np.mean(np.abs(yp - yt))
        rmse = np.sqrt(np.mean((yp - yt) ** 2))
        r2 = 1 - np.sum((yp - yt) ** 2) / (np.sum((yt - yt.mean()) ** 2) + 1e-10)
        print(f"  {col:<24} {mae:>8.4f} {rmse:>8.4f} {r2:>8.4f}")

    print("\n===== PARAMETER RECOVERY =====")
    print(f"  {'Param':<10} {'MAE':>8} {'RMSE':>8} {'R²':>8}")
    for i, col in enumerate(PARAM_COLS):
        pt, pp = P_true[:, i], P_pred[:, i]
        mae = np.mean(np.abs(pp - pt))
        rmse = np.sqrt(np.mean((pp - pt) ** 2))
        r2 = 1 - np.sum((pp - pt) ** 2) / (np.sum((pt - pt.mean()) ** 2) + 1e-10)
        print(f"  {col:<10} {mae:>8.4f} {rmse:>8.4f} {r2:>8.4f}")

    return Y_pred, Y_true, P_pred, P_true


def save_model(best_state, scaler_X, scaler_Y, scaler_P, best_val, save_path):
    os.makedirs(os.path.dirname(save_path), exist_ok=True)
    torch.save({
        "model_state": best_state,
        "scaler_X_mean": scaler_X.mean_,
        "scaler_X_scale": scaler_X.scale_,
        "scaler_Y_mean": scaler_Y.mean_,
        "scaler_Y_scale": scaler_Y.scale_,
        "scaler_P_mean": scaler_P.mean_,
        "scaler_P_scale": scaler_P.scale_,
        "input_cols": INPUT_COLS,
        "target_cols": TARGET_COLS,
        "param_cols": PARAM_COLS,
        "n_in": len(INPUT_COLS),
        "n_params": len(PARAM_COLS),
        "n_out": len(TARGET_COLS),
        "best_val_loss": best_val,
    }, save_path)
    print(f"\nModel saved to {save_path}")


def plot_results(history, Y_pred, Y_true, P_pred, P_true, epochs):
    fig, axes = plt.subplots(1, 3, figsize=(15, 4))
    ep = range(1, epochs + 1)

    axes[0].plot(ep, history["train_total"], color="#5b8df6", lw=1.5, label="Train")
    axes[0].plot(ep, history["val_total"], color="#f5924a", lw=1.5, label="Val")
    axes[0].set_title("Total loss")
    axes[0].legend()
    axes[0].grid(True, alpha=0.3)

    axes[1].plot(ep, history["train_data"], color="#5b8df6", lw=1.5, label="Data")
    axes[1].plot(ep, history["train_params"], color="#3ecf8e", lw=1.5, label="Params")
    axes[1].set_title("Data vs param loss")
    axes[1].legend()
    axes[1].grid(True, alpha=0.3)

    axes[2].plot(ep, history["train_phys"], color="#f56060", lw=1.5)
    axes[2].set_title("Physics loss")
    axes[2].grid(True, alpha=0.3)

    plt.tight_layout()
    plt.savefig("figures/pinn_training_curves.png", dpi=150, bbox_inches="tight")
    plt.close()

    fig, axes = plt.subplots(2, 4, figsize=(16, 8))
    axes = axes.flatten()
    for i, col in enumerate(TARGET_COLS):
        yt, yp = Y_true[:, i], Y_pred[:, i]
        axes[i].scatter(yt, yp, alpha=0.15, s=2, color="#5b8df6")
        lo, hi = min(yt.min(), yp.min()), max(yt.max(), yp.max())
        axes[i].plot([lo, hi], [lo, hi], "r--", lw=1.5)
        r2 = 1 - np.sum((yp - yt) ** 2) / (np.sum((yt - yt.mean()) ** 2) + 1e-10)
        axes[i].set_title(f"{col}\nR²={r2:.3f}", fontsize=9)
        axes[i].set_xlabel("Actual", fontsize=8)
        axes[i].set_ylabel("Predicted", fontsize=8)
        axes[i].grid(True, alpha=0.3)
    plt.tight_layout()
    plt.savefig("figures/pinn_predictions.png", dpi=150, bbox_inches="tight")
    plt.close()
    print("Figures saved to figures/")


if __name__ == "__main__":
    print(f"Device: {DEVICE}")
    df = load_data(CSV_PATH)
    print(f"Loaded {df.shape[0]:,} rows")

    (train_loader, val_loader,
     scaler_X, scaler_Y, scaler_P,
     X_sc, Y_raw, P_raw,
     tr_idx, va_idx) = build_loaders(df, BATCH_SIZE, RANDOM_SEED)

    print(f"Train: {len(tr_idx):,}   Val: {len(va_idx):,}")

    model = PINN(len(INPUT_COLS), len(PARAM_COLS), len(TARGET_COLS)).to(DEVICE)
    print(f"Model parameters: {sum(p.numel() for p in model.parameters()):,}")

    physics_loss_fn = build_physics_loss_fn(scaler_P)

    best_state, best_val, history = train(
        model, train_loader, val_loader, physics_loss_fn, EPOCHS, LR)

    model.load_state_dict(best_state)
    print(f"\nBest val loss: {best_val:.5f}")

    Y_pred, Y_true, P_pred, P_true = evaluate(
        model, X_sc, Y_raw, P_raw, va_idx, scaler_Y, scaler_P)

    save_model(best_state, scaler_X, scaler_Y, scaler_P, best_val, MODEL_SAVE_PATH)

    os.makedirs("figures", exist_ok=True)
    plot_results(history, Y_pred, Y_true, P_pred, P_true, EPOCHS)
