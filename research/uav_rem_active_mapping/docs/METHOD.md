# Cross-frequency and cross-scene REM method

## Problem anchor

The model must reconstruct a 13 m radio map from a continuous UAV trajectory using less than 5% of the 128×128 grid, while transferring across building layouts and five carrier frequencies. Transmitter position and power remain privileged metadata and are never deployment inputs.

## Closest reusable work

| Work | Reusable idea | Limitation for this project |
|---|---|---|
| [UniRM, IEEE JSAC 2025](https://ieeexplore.ieee.org/document/11278023) / [official code](https://github.com/Shirleyue/UniRM) | large-scale pretraining and frequency/height/environment prompts | focuses on radio-map generation; does not solve continuous low-budget active sensing |
| [S2MAE, CVPR 2024](https://openaccess.thecvf.com/content/CVPR2024/html/Li_S2MAE_A_Spatial-Spectral_Pretraining_Foundation_Model_for_Spectral_Remote_Sensing_CVPR_2024_paper.html) | spatial-spectral masked pretraining | spectral imagery is not RF propagation and has no building-aware flight constraints |
| [CAtNIPP, CoRL 2023](https://proceedings.mlr.press/v205/cao23b.html) | global belief context and candidate self-attention for adaptive informative path planning | its belief/reward are not designed for multiband radio maps |
| [Information-theoretic active perception, ICRA 2023 code](https://github.com/JaySparrow/RL-for-active-mapping) | PPO with an information-driven active mapping objective | continuous control and landmark uncertainty do not directly match safe UAV REM sampling |

## Mainline model

The formal model remains one `GeoTransUNet` implementation:

1. radio stem: standardized sparse RSS, observed mask, distance-to-measurement;
2. geometry stem: building footprint, relative building height, flyable mask and ENU coordinates;
3. sampling-pattern transformer: injects the value and spatial distribution of current measurements;
4. continuous condition encoder: `log10(frequency_hz)` and receiver height generate FiLM scale/shift at the bottleneck;
5. shared decoder: outputs RSS mean, aleatoric scale, shadow probability and an auxiliary emitter heatmap.

Unlike a discrete prompt table, continuous conditioning can interpolate between trained frequencies and heights. Unlike a 25-map output head, a conditional query keeps memory constant and supports single-band or multiband receivers with the same checkpoint.

## Stage 1: general propagation pretraining

- Data: layouts 01–24, all five frequencies and all five heights.
- Unit: every `volume × frequency × height` pair is visited once per epoch.
- Visible ratio: 1–25%; random and clustered masks.
- Normalization: independent mean/std per frequency, computed only from pretraining layouts.
- Objective:

```text
Lpre = Lrobust + 0.2 Lmse + 0.1 Lnll + 0.2 Lgradient
       + 0.1 Lmultiscale + 0.05 Lshadow
```

Deep-shadow and shadow-boundary cells receive larger weights. Per-frequency normalization prevents a high-power band from dominating the shared backbone.

## Stage 2: trajectory fine-tuning

- Data: layouts 25–30, 13 m, all five frequencies.
- Sparse input: 0–5%, with 90% continuous trajectories.
- Initialization: pretraining checkpoint and exactly the same pretraining normalization.
- Validation/test: geometry-disjoint layouts 31–32 and 33–34.
- Platform test: held-out Gazebo `urban_block` shards; no platform sample enters training.

## Stage 3: active path planning

The reconstructor is frozen first. A candidate-attention PPO policy observes RSS mean, uncertainty, shadow probability, observed mask, building/flyable masks, UAV position, remaining measurements and remaining path budget. It selects a reachable unmeasured candidate or STOP; A* converts the selected goal to collision-free waypoints.

For a fixed hidden probe set, the map reward is

```text
r_map,t = (RMSE_t - RMSE_{t+1}) / S_train
r_t = w_map r_map,t - w_dist path_cost_t - w_repeat I_repeat - w_fail I_fail
```

The probe cells never belong to the candidate lattice. Sionna GT is used for training reward only and is unavailable to the deployed policy.

## Claims and necessary ablations

| Claim | Required comparison |
|---|---|
| Cross-scene transfer | held-out layouts and held-out `urban_block`; no-geometry ablation |
| Cross-frequency sharing | shared conditional model vs five independent models vs no-frequency-condition model |
| Deep-shadow reconstruction | no-shadow-weight and no-boundary-weight ablations |
| Active sampling | PPO vs random trajectory, lawnmower, uncertainty greedy and CAtNIPP-style policy under identical calls/path budget |
