# AlcoholTwin

A physics-informed digital twin for personalized alcohol pharmacokinetics, BAC prediction, brain alcohol exposure, and risk assessment.

## What this is

AlcoholTwin simulates how alcohol moves through the human body using a system of four coupled ordinary differential equations — stomach, intestine, bloodstream, and brain. A physics-informed neural network (PINN) trained on 50,000 synthetic subjects learns to map observable characteristics (weight, height, age, sex, food, drinking pattern) to personalized physiological parameters and clinical risk scores.

The project combines chemical engineering, reaction engineering, pharmacokinetics, and deep learning into a single interpretable pipeline.

## Project structure

```
AlcoholTwin/
├── model/
│   ├── simulator.py          ODE-based alcohol pharmacokinetics model
│   ├── train_pinn.py         PINN training pipeline
│   └── pinn_alcohol_model.pt Trained model weights + scalers
├── data/
│   └── generate_population.py  Synthetic population generator (50k subjects)
├── dashboard/
│   ├── dashboard.html          Interactive user-facing tool
│   └── validation_comparison.html  Model vs Jones (1984) published data
├── figures/
│   ├── validation_jones1994.png
│   ├── population_validation.png
│   └── dose_distribution.png
└── requirements.txt
```

## How to run

**1. Install dependencies**
```bash
pip install -r requirements.txt
```

**2. Generate synthetic population**
```bash
python data/generate_population.py
```
This produces `data/synthetic_alcohol_population_v2.csv` (~50,000 rows, ~3 min runtime).

**3. Train the PINN**
```bash
python model/train_pinn.py
```
GPU recommended (Google Colab T4 works well). Trains in ~5 minutes on GPU, ~40 minutes on CPU.

**4. Open the dashboard**

Open `dashboard/dashboard.html` in any browser. No server required.

## Model overview

### Compartment model (ODEs)

```
dS/dt  = F(t) - kg × S                     stomach
dI/dt  = kg × S - ka × I                   intestine
dB/dt  = ka × I - Vmax×B/(Km+B)            blood (Michaelis-Menten liver)
dBr/dt = kBBB × (B/Vd - Br)               brain (BBB transport)
```

### Key parameters

| Parameter | Meaning | Source |
|-----------|---------|--------|
| TBW | Total body water (volume of distribution) | Watson et al. (1980) |
| LBM | Lean body mass | Boer (1984) |
| Vmax | Maximum liver metabolism rate | Norberg et al. (2003) |
| Km | Michaelis constant | Wilkinson et al. (1977) |
| kBBB | Blood-brain barrier transport | Jones & Jonsson (1994) |
| kg | Gastric emptying rate | Horowitz et al. (1989) |

### PINN architecture

Observable inputs → Shared trunk → Parameter head → [Vmax, Km, kBBB, kg, ka]
                                                          ↓
                                                    Output head → [peak BAC, BrAC, recovery time, 5 risk scores]

The output head receives only the estimated physiological parameters — not the raw inputs — enforcing an information bottleneck that makes the physics the mandatory pathway to all predictions.

### Validation

Validated against Jones (1984): 48 healthy fasting males, 0.68 g/kg ethanol, 20-minute consumption.
- MAE: 0.009% BAC across the 7-hour profile
- Peak error: −0.006% (model slightly underestimates due to Watson TBW formula)

### Performance

| Output | R² |
|--------|-----|
| Peak BAC | 0.994 |
| Peak brain alcohol | 0.994 |
| Recovery time | 0.967 |
| Blackout risk | 0.980 |
| Pass-out risk | 0.974 |

## References

- Jones, A.W. (1984). Interindividual variations in the disposition and metabolism of ethanol. *Alcohol and Alcoholism*, 19(4), 353–360.
- Jones, A.W. & Jonsson, K.Å. (1994). Food-induced lowering of blood-ethanol profiles. *Journal of Forensic Sciences*, 39(4), 1084–1093.
- Watson, P.E. et al. (1980). Total body water volumes for adult males and females. *American Journal of Clinical Nutrition*, 33(1), 27–39.
- Norberg, Å. et al. (2003). Role of variability in explaining ethanol pharmacokinetics. *Clinical Pharmacokinetics*, 42(1), 1–31.
- Wilkinson, P.K. et al. (1977). Pharmacokinetics of ethanol after oral administration. *Journal of Pharmacokinetics and Biopharmaceutics*, 5(3), 207–224.
- Horowitz, M. et al. (1989). Effect of ethanol on gastric emptying in man. *Gastroenterology*, 97(2), 338–343.
- Wetherill, R.R. & Fromme, K. (2011). Alcohol-induced blackouts. *Alcoholism: Clinical and Experimental Research*, 35(6), 1055–1065.

## Disclaimer

This is a research prototype. It is not a medical device and must not be used to make decisions about driving or any safety-critical activity.
