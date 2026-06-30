import numpy as np
import pandas as pd
from scipy.stats.qmc import LatinHypercube
import time
import sys
import os

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from model.simulator import simulate

N_SUBJECTS = 50000
RANDOM_SEED = 42
OUTPUT_CSV = "data/synthetic_alcohol_population_v2.csv"


def generate_population(n=N_SUBJECTS, seed=RANDOM_SEED, output_path=OUTPUT_CSV):
    sampler = LatinHypercube(d=7, seed=seed)
    lhs = sampler.random(n=n)

    weight_arr = 50 + lhs[:, 0] * 70
    height_arr = 150 + lhs[:, 1] * 45
    age_arr = 18 + lhs[:, 2] * 47
    gender_arr = (lhs[:, 3] >= 0.5).astype(int)
    dur_arr = 0.25 + lhs[:, 4] * 3.75
    meal_cal_arr = lhs[:, 5] * 1000
    meal_fat_arr = lhs[:, 6] * 60

    rng = np.random.default_rng(seed)
    dose_raw = rng.lognormal(mean=3.5, sigma=0.6, size=n)
    dose_arr = np.clip(dose_raw, 10, 120)

    vmax_mult = np.clip(rng.normal(1.0, 0.10, n), 0.7, 1.3)
    km_mult = np.clip(rng.normal(1.0, 0.075, n), 0.7, 1.3)
    kbbb_mult = np.clip(rng.normal(1.0, 0.10, n), 0.7, 1.3)
    kg_mult = np.clip(rng.normal(1.0, 0.075, n), 0.7, 1.3)

    records = []
    failed = 0
    t0 = time.time()

    for i in range(n):
        gender = "male" if gender_arr[i] == 1 else "female"
        result = simulate(
            weight=weight_arr[i],
            height=height_arr[i],
            age=int(age_arr[i]),
            gender=gender,
            alcohol_dose=dose_arr[i],
            drinking_duration=dur_arr[i],
            meal_calories=meal_cal_arr[i],
            meal_fat_g=meal_fat_arr[i],
            vmax_mult=vmax_mult[i],
            km_mult=km_mult[i],
            kbbb_mult=kbbb_mult[i],
            kg_mult=kg_mult[i],
        )

        if result is not None:
            row = {
                "weight": round(weight_arr[i], 2),
                "height": round(height_arr[i], 2),
                "age": int(age_arr[i]),
                "gender": gender,
                "alcohol_dose_g": round(dose_arr[i], 2),
                "drinking_duration": round(dur_arr[i], 3),
                "meal_calories": round(meal_cal_arr[i], 1),
                "meal_fat_g": round(meal_fat_arr[i], 2),
                "TBW": round(result["TBW"], 3),
                "LBM": round(result["LBM"], 3),
                "Vd": round(result["Vd"], 3),
                "Vmax": round(result["Vmax"], 4),
                "Km": round(result["Km"], 5),
                "kBBB": round(result["kBBB"], 4),
                "kg": round(result["kg"], 4),
                "ka": round(result["ka"], 4),
                "peak_BAC_pct": round(result["peak_BAC_pct"], 5),
                "time_to_peak_BAC": round(result["time_to_peak_BAC"], 3),
                "peak_BrAC_pct": round(result["peak_BrAC_pct"], 5),
                "time_to_peak_BrAC": round(result["time_to_peak_BrAC"], 3),
                "BAC_brain_lag_hr": round(result["BAC_brain_lag_hr"], 3),
                "recovery_time_hr": round(result["recovery_time_hr"], 3),
                "max_dBAC_dt": round(result["max_dBAC_dt"], 5),
                "rate_shift": round(result["rate_shift"], 5),
                "P_mild_pct": round(result["P_mild_pct"], 2),
                "P_moderate_pct": round(result["P_moderate_pct"], 2),
                "P_severe_pct": round(result["P_severe_pct"], 2),
                "P_blackout_pct": round(result["P_blackout_pct"], 2),
                "P_passout_pct": round(result["P_passout_pct"], 2),
                "max_safe_dose_g": round(result["max_safe_dose_g"], 2),
                "max_safe_drinks": round(result["max_safe_drinks"], 3),
            }
            records.append(row)
        else:
            failed += 1

        if (i + 1) % 10000 == 0:
            elapsed = time.time() - t0
            eta = (n - i - 1) / ((i + 1) / elapsed)
            print(f"  {i+1}/{n}  {elapsed/60:.1f}min elapsed  ETA {eta/60:.1f}min")

    df = pd.DataFrame(records)
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    df.to_csv(output_path, index=False)

    print(f"\nSaved {len(records):,} subjects to {output_path}")
    print(f"Failed simulations: {failed}")
    print(f"Total time: {(time.time()-t0)/60:.1f} min")
    return df


if __name__ == "__main__":
    generate_population()
