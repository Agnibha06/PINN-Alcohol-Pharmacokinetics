import numpy as np
from scipy.integrate import solve_ivp


def sigmoid(x, threshold, k):
    return 1.0 / (1.0 + np.exp(-k * (x - threshold)))


def compute_body_composition(weight, height, age, gender):
    if gender.lower() == "male":
        TBW = 2.447 - 0.09516 * age + 0.1074 * height + 0.3362 * weight
        LBM = 0.407 * weight + 0.267 * height - 19.2
    else:
        TBW = -2.097 + 0.1069 * height + 0.2466 * weight
        LBM = 0.252 * weight + 0.473 * height - 48.3
    return max(TBW, 10.0), max(LBM, 10.0)


def compute_gastric_params(meal_calories, meal_fat_g):
    fat_penalty = 1.0 + 0.004 * meal_fat_g
    kg = np.clip((1.8 / fat_penalty) * np.exp(-0.0008 * meal_calories), 0.1, 5.0)
    ka = np.clip(1.2 * np.exp(-0.0003 * meal_calories), 0.1, 5.0)
    return kg, ka


def blackout_risk_rate_adjusted(BrAC_pct, BAC_pct, time_arr):
    peak_idx = np.argmax(BAC_pct)
    asc_BAC = BAC_pct[:peak_idx + 1]
    asc_time = time_arr[:peak_idx + 1]

    if len(asc_BAC) > 1:
        dBAC_dt = np.gradient(asc_BAC, asc_time)
        max_rate = float(np.max(dBAC_dt))
    else:
        max_rate = 0.0

    rate_shift = np.clip(0.20 * (max_rate - 0.03), 0.0, 0.025)
    threshold = max(0.035, 0.060 - rate_shift)
    threshold_po = max(0.055, 0.090 - rate_shift * 1.5)

    P_blackout = sigmoid(BrAC_pct, threshold=threshold, k=200)
    P_passout = sigmoid(BrAC_pct, threshold=threshold_po, k=250)

    return (
        float(np.max(P_blackout)) * 100,
        float(np.max(P_passout)) * 100,
        float(max_rate),
        float(rate_shift),
    )


def simulate(
    weight,
    height,
    age,
    gender,
    alcohol_dose,
    drinking_duration,
    meal_calories,
    meal_fat_g,
    vmax_mult=1.0,
    km_mult=1.0,
    kbbb_mult=1.0,
    kg_mult=1.0,
    t_end=12.0,
    n_points=300,
):
    TBW, LBM = compute_body_composition(weight, height, age, gender)
    Vd = TBW

    Vmax = np.clip(0.10 * LBM * vmax_mult, 0.5, 20.0)
    Km = np.clip(0.05 * Vd * km_mult, 0.01, 5.0)
    kBBB = 1.5 * kbbb_mult

    kg, ka = compute_gastric_params(meal_calories, meal_fat_g)
    kg = np.clip(kg * kg_mult, 0.1, 5.0)

    feed_rate = alcohol_dose / drinking_duration
    t_span = (0, t_end)
    t_eval = np.linspace(0, t_end, n_points)

    def ode_system(t, y):
        S, I, B, Br = y
        F = feed_rate if t <= drinking_duration else 0.0
        C_blood = B / Vd
        rm = (Vmax * B) / (Km + B)
        return [
            F - kg * S,
            kg * S - ka * I,
            ka * I - rm,
            kBBB * (C_blood - Br),
        ]

    sol = solve_ivp(
        ode_system,
        t_span,
        [0.0, 0.0, 0.0, 0.0],
        t_eval=t_eval,
        method="RK45",
        rtol=1e-4,
        atol=1e-6,
    )

    if not sol.success:
        return None

    BAC = (sol.y[2] / Vd) / 10.0
    BrAC_pct = sol.y[3] / 10.0
    time = sol.t

    peak_bac = float(np.max(BAC))
    peak_time_bac = float(t_eval[np.argmax(BAC)])
    peak_brac = float(np.max(BrAC_pct))
    peak_time_br = float(t_eval[np.argmax(BrAC_pct)])

    idx = np.argmax(BAC)
    post_BAC = BAC[idx:]
    post_time = t_eval[idx:]
    below = np.where(post_BAC < 0.02)[0]
    recovery = float(post_time[below[0]]) if len(below) > 0 else t_end

    P_mild = float(np.max(sigmoid(BrAC_pct, 0.020, 200))) * 100
    P_moderate = float(np.max(sigmoid(BrAC_pct, 0.040, 150))) * 100
    P_severe = float(np.max(sigmoid(BrAC_pct, 0.060, 150))) * 100
    P_blackout, P_passout, max_rate, rate_shift = blackout_risk_rate_adjusted(
        BrAC_pct, BAC, time
    )

    max_safe_g = float(np.clip((0.06 * Vd * 10) / 0.94, 5.0, 120.0))

    return {
        "time": time,
        "BAC": BAC,
        "BrAC_pct": BrAC_pct,
        "peak_BAC_pct": peak_bac,
        "time_to_peak_BAC": peak_time_bac,
        "peak_BrAC_pct": peak_brac,
        "time_to_peak_BrAC": peak_time_br,
        "BAC_brain_lag_hr": peak_time_br - peak_time_bac,
        "recovery_time_hr": recovery,
        "max_dBAC_dt": max_rate,
        "rate_shift": rate_shift,
        "P_mild_pct": P_mild,
        "P_moderate_pct": P_moderate,
        "P_severe_pct": P_severe,
        "P_blackout_pct": P_blackout,
        "P_passout_pct": P_passout,
        "max_safe_dose_g": max_safe_g,
        "max_safe_drinks": max_safe_g / 14.0,
        "TBW": TBW,
        "LBM": LBM,
        "Vd": Vd,
        "Vmax": Vmax,
        "Km": Km,
        "kBBB": kBBB,
        "kg": kg,
        "ka": ka,
    }
