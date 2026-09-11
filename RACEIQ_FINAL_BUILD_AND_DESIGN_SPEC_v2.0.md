# RaceIQ 2026 — Final Build & Design Specification v2.0

**TrackShift 2026 · Problem 1: Energy & Overtake Intelligence · 2-person team**
**Today: 4 Sep 2026 · Finale: 12–13 Sep 2026 · Organizer-approved full pre-build**

---

## 0. How to use this document

- This is the **one file** to work from. All earlier planning is merged here.
- **WorkBuddy instruction:** read this entire document, create the repo scaffold + `config/*.json`, then implement **Phase 0 → Phase 10 in strict order**. Run `pytest` after each phase. Do not start the next phase until the current phase tests pass.
- Design perspective is in **§3** — the UI is the credibility layer and must be built exactly to that spec (minimalist, no emojis).
- **Estimation vs simulation:** the main demo is **REPLAY of a real cached 2026 race**. The battery is **estimated/reconstructed** from real telemetry + FIA rules — never called "simulated". `SIMULATION` mode exists but is secondary and clearly labelled.

---

## 1. Executive summary & thesis

### The paradox (anchor of the pitch)
2026 F1 power unit: **MGU-K 350 kW**, **MGU-H deleted**, 50/50 ICE/electric. Battery usable window = **4 MJ** (Art. 5.4.8); harvest up to **9 MJ/lap** (5.4.9).
`4 MJ ÷ 350 kW = 11.4 seconds` — the buffer empties in 11.4 s and cycles ~2× per lap.
Harvest is **circuit-limited**: brake-only recovery ≈ **Baku 7.1 MJ, Monza 3.3 MJ, Melbourne 2.9 MJ**.
**Overtake Mode** (replaces DRS) is proximity-gated: within the FIA event **Detection Gap** at the Detection Line, the chasing car gets **+0.5 MJ** and a higher deployment speed on the following lap.
**SoC / ERS / MGU-K power / Active Aero are NOT public.**

### One-line thesis
> *"The battery is a 4 MJ window that drains in 11.4 s. Nobody publishes SoC — so RaceIQ reconstructs it from public telemetry + the FIA rulebook, prices every overtake as a legal bet that repays its energy debt, and re-runs on an electric bus."*

### Why this wins
- **Novel:** SoC inference from public data under partial observability + counter-harvest trap.
- **Compliant:** full FIA rule ledger + certificate (the problem explicitly says "rule compliance").
- **Impactful:** measurable vs Greedy/Conservative baselines.
- **Transferable:** EV-bus primary (PM e-Bus Sewa), microgrid secondary.
- **Fast:** Tier-1 DP **<10 ms** → edge-deployable.

---

## 2. Terminology (plain English)

| Term | What it means | Why it matters |
|---|---|---|
| **SoC (State of Charge)** | Battery charge level, expressed as a **0–4 MJ window** (shown as 0–100% of that window). | The hidden core variable. Empties in 11.4 s at 350 kW, cycles ~2×/lap. We **estimate** it. |
| **ERS (Energy Recovery System)** | The hybrid system. 2026 has **only MGU-K** (MGU-H deleted). Two jobs: **harvest** (recover under braking) and **deploy** (send to wheels). Modes: **Harvest / Balance / Deploy**. | Decides whether a car is saving or spending. Inferred from telemetry. |
| **Clipping / Superclipping** | Battery empty → car "clips": driver at **full throttle but speed stops rising** because MGU-K steals engine power to recharge. Superclipping = clipping at full throttle on a straight. | **Observable in public telemetry.** This is how we prove the estimated SoC is right. |
| **8-state HMM** | Hidden Markov Model with 8 hidden states: `ERS ∈ {H, M, Lharvest, Lderate}` × `Overtake ∈ {available, spent}`. Infers a **rival's** hidden battery/mode from public signals. Uses forward algorithm → belief (probabilities). | Rivals never publish SoC. Turns "he looks slow" into `P(Lharvest)` (trap) vs `P(Lderate)` (opportunity). |
| **Tier-1 DP / Pareto frontier** | Dynamic Programming inside one lap: state = `(10 m segment, 0.1 MJ SoC bin)`, action = power `{0,150,250,350} kW` filtered by FIA rules. Output = **Pareto frontier**: min lap time vs net energy spent. Runs **<10 ms**. | Gives the **exchange rate between joules and seconds** on this circuit — the "price list" Tier-2 uses. |
| **Tier-2 (MPC)** — *"Tier 2", not tyre* | Model Predictive Control / scenario-tree optimizer over the **next 8–12 laps**. Consumes Tier-1 frontier → posture **ATTACK / NEUTRAL / HARVEST / DEFEND**. Re-plans every lap. | Race has long memory (position, gaps, tyres, pit, SC). Battery has almost no memory. Decomposing makes it solvable. |
| **Tyre** | Compound + age are **observed/public** (OpenF1 stints). Fed as input to `P(pass)` and MPC. | Stays **observed**, not in the hidden HMM — keeps HMM to 8 states. |
| **Overtake EV engine** | At the Detection Line, if gap ≤ Detection Gap, prices the overtake: `EV = P(pass)·points − repass risk − repayment cost − λ·illegal`. Outputs **GO / HOLD** + breakdown. | The literal answer to "risk-reward ratio of overtake windows". |
| **Baselines** | **Greedy** (attack whenever gap ≤ Detection Gap) and **Conservative** (harvest/save late laps), run on the same race replay. Optional **Oracle** (true hidden state, simulation only). | Proves **measured impact** — RaceIQ must beat both in net time/positions. |
| **Active Aero / zaero** | Movable front+rear wings, **Straight Mode** (low drag) / **Corner Mode**. Not proximity-gated; available to all in FIA zones. Gives speed **independent of battery** → basis of the trap. | **Inferred** from speed residual in aero zones (no public channel). Label as inferred. |
| **Detection Gap** | Gap required at the Detection Line to get Overtake Mode. **Event-specific**, not universally 1.000 s. | Elligibility rule. Parameterise from FIA event note (default 1.0 s). |
| **Overtake Mode** | The **+0.5 MJ** proximity boost replacing DRS; also allows full 350 kW to ~337 km/h vs leader tapering from 290 km/h. | The overtaking tool we must manage. |
| **Boost** | Driver-controlled electric boost, usable anywhere; race cap **+150 kW** (post-Miami). | Separate from Overtake. Included in DP actions. |
| **Counter-harvest trap** | Rival looks slow because it is **deliberately harvesting** (`Lharvest`) while running Active Aero — so it is building a hidden reserve to attack you, not empty. Opposite of `Lderate`. | Prevent a fatal bad bet. Detected via HMM posterior + `zaero` + in-zone. |
| **Lharvest vs Lderate** | `Lharvest` = saving on purpose (trap). `Lderate` = genuinely at SOC ceiling, full throttle but no electrical power (opportunity). | Opposite meanings; separated by `δthrottle` (super-clipping duration fraction). |
| **Repayment cost** | Time lost later to harvest back the spent energy: `laps_of_harvest × (T_harvest − T_neutral)`. Circuit-dependent (Monza repays slower than Baku). | The "energy debt interest rate". |
| **Repass / yo-yo risk** | After you pass, the passed car is now inside the Detection Gap **behind you** and gets Overtake against you — you can be re-passed immediately. | Real 2026 phenomenon; almost nobody models it. |
| **REPLAY / SIMULATION / LIVE** | **REPLAY** = real cached race (main demo). **SIMULATION** = synthetic what-if (secondary, labelled). **LIVE** = best-effort OpenF1 poll (still estimated, no ERS channel). | Demo honesty. |

---

## 3. Design perspective (UI/UX) — the credibility layer

### 3.1 Design goals
- A **professional pit-wall telemetry terminal**, not a flashy AI toy.
- **Minimalist, modern, dark, data-dense, calm.**
- **No emojis.** No 🟢🟡🔴, no 📻🌦️. Use **text chips** (`HARVEST` / `BALANCE` / `DEPLOY`).
- Every energy number carries the honest watermark.
- Judges believe a system that looks like real race-engineering software.

### 3.2 Design system
- **Background:** `#0F1115` · **Card surface:** `#161A22` · **Border:** `#242A34`
- **Primary text:** `#E6E8EB` · **Muted text:** `#8A93A0`
- **Mode colours:** Harvest `#2E7D5B` (green text), Balance `#B8860B` (amber), Deploy `#C0392B` (red)
- **Status:** PASS `#2E7D5B`, FAIL `#C0392B`
- **Team colours:** only for driver identity (left border / dot)
- **Font:** `Inter, sans-serif`. Small caps / uppercase for labels with letter-spacing. **Tabular numbers** for telemetry.
- **Charts:** Plotly `template="plotly_dark"`, thin lines, no heavy gridlines, minimal margins.
- **Spacing:** 8 px grid; card radius 6–8 px; 1 px borders.
- **Watermark (footer, muted):** `Estimated SoC — inferred from public telemetry + FIA rules. No public ERS/SoC telemetry exists.`

### 3.3 Information architecture / layout
**Wide 3-column Streamlit layout.**

- **Header bar:** `EVENT · SESSION · LAP 34/58 · TRACK GREEN · WEATHER` + mode toggle text (`REPLAY` / `SIMULATION` / `LIVE`). No icons.
- **Left column — Timing tower (22 rows):**
  `POS` · `DRIVER` (team colour left border) · `INTERVAL` · thin **Estimated SoC bar** (0–100% of 4 MJ) · **mode chip** (`HARVEST`/`BALANCE`/`DEPLOY`) · `LAP DELTA`. Selected driver row highlighted with subtle border.
- **Centre column — Track map + Overtake Decision Card (hero):**
  - Clean Plotly/SVG circuit outline; driver dots (team colours); dashed **Detection Line** + **Activation Line**; Overtake zone shaded subtly.
  - **Decision card:** `GAP AT DETECTION: 0.8 s · ELIGIBLE` → **BIG recommendation** `ATTACK` / `HOLD` / `HARVEST` / `DEFEND` (large, uppercase, colour-coded text) → EV breakdown (bars/text): `P(pass) 58%`, `Points gain`, `Repayment cost 0.4 s`, `Repass risk 22%`, `Compliance OK` → **Why line:** `58% pass, costs 0.4 s to recharge, 22% repass risk, legal → GO` → **Trap banner** (if triggered): plain text `COUNTER-HARVEST TRAP — rival conserving in aero zone` and recommendation flips to `HOLD`.
- **Right column — Compare + Compliance:**
  - **Driver comparison:** two selected drivers side-by-side; Estimated SoC bars; `ΔSoC`; gap; mode chips.
  - **Compliance board:** rule name + `PASS` / `FAIL` text — `ΔSoC 4 MJ — PASS`, `Harvest ≤9 MJ/lap — PASS`, `power_to_propel — PASS`, `zone 350/250 kW — PASS`, `Boost +150 kW — PASS`, `start 50 km/h — PASS`, `pit 100 kJ — PASS`, `torque 500 Nm — PASS`.
- **Bottom — charts (clean):**
  - Estimated SoC vs lap (top 5 drivers, thin lines)
  - Speed trace with **clipping flags** (vertical dashed lines labelled `CLIPPING`)
  - Cumulative time delta: **RaceIQ vs Greedy vs Conservative** (RaceIQ line visibly better)
- **Footer:** watermark text.

### 3.4 Component specs
- **SoC bar:** 0–100% of the 4 MJ window; muted fill; label `Estimated`. No emoji.
- **Mode chip:** text only, coloured per state (green/amber/red). Not emoji.
- **Decision card:** the hero. Large recommendation text; EV breakdown as bars or compact text; plain-language Why line; trap banner as text.
- **Compliance board:** text `PASS` / `FAIL`. No emoji.
- **Mode toggle:** text `REPLAY` / `SIMULATION` / `LIVE`. Active mode plain text.
- **Scenario Mode (inspired by f1-energy-dash UX):** pre-built narrative (e.g. `VER vs NOR — Albert Park`) demonstrating an overtake opportunity; computed with our own estimates, not scraped data.

### 3.5 Interaction flow / states
1. Default **REPLAY** of a real cached 2026 race (Melbourne / Shanghai / Bahrain).
2. User selects the **ego driver**; system runs observer + HMM on relevant rivals.
3. As replay approaches the **Detection Line**: if `gap ≤ Detection Gap` → `ELIGIBLE`.
4. Overtake EV engine computes; card updates with recommendation + breakdown.
5. If trap → warning + `HOLD`. If illegal → compliance `FAIL` + `HOLD`.
6. Bottom charts update; clipping flags appear on the speed trace.
7. `SIMULATION` tab: synthetic what-if (clearly labelled). `EV BUS` tab: transfer module.

### 3.6 Why this design wins judges
- Looks like real race-engineering software → **trust**.
- **No emojis** = maturity; emoji UI = hackathon toy.
- **Watermark** = intellectual honesty (a differentiator, not a weakness).
- Data-dense but calm; the hero decision card focuses attention on the actual bet.

### 3.7 Streamlit implementation notes
- `st.set_page_config(layout="wide", page_title="RaceIQ 2026")`
- Custom dark CSS via `st.markdown(..., unsafe_allow_html=True)`
- `st.columns([1.1, 1.6, 1.1])` for the 3-column body
- `plotly.graph_objects` for map/charts; `template="plotly_dark"`
- `st.session_state` for selected driver, lap, mode
- Tabs for `REPLAY` / `SIMULATION` / `EV BUS`
- Footer watermark on every page

---

## 4. System architecture & processing flow

### Why layers / tiers
- **Battery** has almost **no memory**: 4 MJ, drains 11.4 s, cycles ~2×/lap → energy decisions are near-myopic.
- **Race** has **long memory**: position, gaps, tyres, pit windows, safety car → strategy over laps.
- Solving both in one giant DP explodes. Decompose:
  - **Tier 1** (inside one lap): energy↔time exchange rate.
  - **Tier 2** (next 8–12 laps): posture.
  - **Tier 3** (race): pit windows, points, weather.
- Clean interface: **Tier-2 consumes the Tier-1 Pareto frontier**.

### Processing layers (pipeline)
| Layer | What it does | Why needed |
|---|---|---|
| Ingest | Load cached real race + OpenF1 gaps/SC/weather | No data, no system |
| Segmentation | Cut lap into braking / exit / straight / coast using TUMFTM geometry | Harvest/deploy physics differ by corner |
| SoC observer | Estimate battery for all 22 cars by energy balance + rule clamps | Battery is hidden |
| ERS + clipping | Label Harvest/Balance/Deploy; flag clipping | Behaviour + validation signal |
| Opponent belief (8-state HMM) + trap | Infer rival ERS mode/Overtake status; detect counter-harvest trap | "Looks slow" ≠ "empty" |
| Compliance ledger | Check every candidate plan vs FIA stack | Problem demands rule compliance |
| Tier-1 DP | Optimal power per segment → Pareto frontier | Energy→time price list, <10 ms |
| Tier-2 MPC | Choose ATTACK/NEUTRAL/HARVEST/DEFEND over horizon | Race has long memory |
| Overtake EV | Price the specific bet at detection line | Problem asks risk-reward |
| UI + baselines + transfer | Show, prove, generalize | Demo, impact, real-world |

### Runtime flow
`FastF1 cache + OpenF1 + TUMFTM + FIA note + rules JSON`
→ `ingest.load_*()` → clean DataFrames
→ `track.build_segments()` → segment table
→ `inference.SocObserver.update()` → est SoC, ERS mode, clipping (all 22)
→ `inference.OpponentBelief.update()` → rival belief + trap flag
→ `rules.ComplianceLedger.check()` → green/red certificate
→ `optimize.Tier1DP.solve()` → Pareto frontier
→ `optimize.Tier2MPC.recommend()` → posture
→ `decision.OvertakeEV.evaluate()` → GO/HOLD + breakdown
→ `ui.main` (Streamlit) + `baselines.compare()` + `transfer.EVBusSolver`

### Compute / scalability (already in the build)
| Component | Runs on | Cost | Why this scope |
|---|---|---|---|
| Physics SoC observer + ERS + clipping | **All 22 cars** | ~free (arithmetic) | Timing tower needs 22 SoC bars; also a feature for LR. `22×500` segments `<1 ms`. |
| 8-state HMM belief + trap | **Only relevant rivals: next 2 ahead + previous 2 behind** (~4) | small | Only these affect attack/defend. All-22 HMM gives no decision value and hurts accuracy (identifiability). |
| Tier-1 DP / frontier | **Ego car only (1)** | **<10 ms** | Deployment decision is for our car. Re-run on demand if user selects another driver. |
| Tier-2 MPC | Ego car | small | Posture is for our car. |
| Overtake EV | Ego vs 1 defender | small | Prices the one bet. |
| Baselines | All cars, offline | offline | Comparison table only. |

**Later in-team deployment:** team knows its **own** SoC exactly; system only **infers rivals** (still only the relevant window). Own-car estimate becomes exact → higher accuracy, same low compute.

### Module signatures (implement exactly)
```python
load_fastf1_session(year, event, session, cache_dir) -> SessionData
fetch_openf1(endpoint, params) -> pd.DataFrame
pre_cache_sessions(events, cache_dir) -> None
build_segments(track_geo, speed_trace) -> list[Segment]

class SocObserver:
    def update(self, telemetry_row, segment) -> SocState   # soc_mj, mode, clipping_flag

class ErsClassifier:
    def classify(self, soc_state, throttle, brake) -> str   # Harvest/Balance/Deploy

class ClippingDetector:
    def detect(self, speed, throttle, prev_speed) -> bool   # full throttle & speed flat

class OpponentBelief:
    def __init__(self, n_states=8)
    def update(self, emissions) -> Belief   # rival ERS bin, Overtake status, trap_prob

class ComplianceLedger:
    def __init__(self, config)
    def check(self, plan, speed_kph, lap) -> ComplianceResult

solve_lap_dp(segments, config, soc_bins=40) -> ParetoFrontier   # <10 ms
class Tier2MPC:
    def __init__(self, frontier, config)
    def recommend(self, state, horizon=10) -> Posture

class PassModel:
    def fit(self, X, y) -> None
    def predict_proba(self, features) -> float   # sklearn LogisticRegression

class OvertakeEV:
    def __init__(self, config, pass_model)
    def evaluate(self, state, frontier) -> OvertakeDecision   # GO/HOLD + breakdown

class EVBusSolver:
    def __init__(self, config)
    def recommend(self, bus_state) -> BusRecommendation
```
Streamlit `ui/main.py` renders per **§3**.

---

## 5. Models — what is trained vs not

### The core rule
> **We train NO model to predict SoC.** There is no ground-truth battery label, so SoC comes from the **deterministic physics observer** (energy balance clamped by FIA rules). It is estimation, not machine learning.

| Component | Trained? | Type | Library |
|---|---|---|---|
| SoC observer | No | Deterministic physics + rule clamps | numpy |
| ERS mode / clipping | No | Rule-based (throttle vs speed) | numpy/pandas |
| 8-state HMM belief | No (analytic init) | HMM forward algorithm (custom numpy) | no `hmmlearn.fit` |
| Counter-harvest trap | No | Threshold on HMM posterior | numpy |
| Tier-1 DP / frontier | No | Dynamic programming | numpy |
| Tier-2 MPC | No | Scenario-tree optimizer | numpy |
| EV-bus solver | No | Same DP/MPC, bus config | numpy |
| **Logistic Regression `P(pass)`** | **YES** | Supervised binary classifier | `sklearn.linear_model.LogisticRegression` + `CalibratedClassifierCV` |
| Optional MLP for `P(pass)` | Stretch only | Small net (if LR underperforms) | `sklearn.neural_network.MLPClassifier` or torch |

- **No PyTorch / DQN in the core.** The prior-art paper used a DQN; we **replaced** it with interpretable DP + MPC. PyTorch is only an optional stretch for the pass classifier; `sklearn` LR is preferred.
- **Bandits are NOT used to predict battery/SoC.** Predicting a rival's battery is a **hidden-state filtering** problem (HMM), not a bandit problem. Bandit/multi-armed is only an *optional* future add for online policy selection among candidate strategies — not for state inference. Never say "bandit predicts battery".

### The one trained model: `P(pass)`
- **Features:** `gap_ahead_s`, `closing_speed_kph`, `straight_remaining_m`, `tyre_age_delta_laps`, `own_est_soc`, `rival_est_soc`, `rival_P_Lderate`, `rival_P_Lharvest`, `trap_flag`, `overtake_mode_active`, `circuit_harvest_potential_mj`, `laps_remaining`.
- **Labels:** real 2026 overtakes from **OpenF1 `position`** — at a detection event, if the attacker's position number improves and they are ahead of that defender after the straight/lap → `y=1`, else `y=0`.
- **Training sketch:**
```python
from sklearn.linear_model import LogisticRegression
from sklearn.calibration import CalibratedClassifierCV
from sklearn.model_selection import GroupKFold
from sklearn.metrics import roc_auc_score, brier_score_loss

base = LogisticRegression(max_iter=1000, class_weight='balanced', C=1.0, solver='lbfgs')
model = CalibratedClassifierCV(base, method='isotonic', cv=GroupKFold(n_splits=3))
model.fit(X, y, groups=groups)          # groups = race_id / circuit
p_pass = model.predict_proba(X_new)[:, 1]
print("AUC:", roc_auc_score(y_test, p_pass), "Brier:", brier_score_loss(y_test, p_pass))
```
- **Why LR:** interpretable (judges see gap is the strongest negative coefficient), outputs calibrated probabilities the EV formula needs, works with a few hundred samples.
- **Fallback:** pre-train on Simulation-mode synthetic races (where pass success is controlled), then evaluate/fine-tune on real labelled events.

### HMM details
- 8 states: `ERS ∈ {H, M, Lharvest, Lderate}` × `Overtake ∈ {available, spent}`.
- Forward algorithm: `α_t(j) = P(o_t|j) · Σ_i α_{t-1}(i)·T_ij`.
- Emission matrix set **analytically** (Gaussian for `∆vtrap`, `δthrottle`, `∆bbrake`, `σ²speed`; Bernoulli for `zaero`) — parameters adapted from domain knowledge / paper Tables 1,2,8.
- Transition asymmetry: `Lharvest` can go to M/H under burn; `Lderate` cannot bypass recovery.
- **No Baum-Welch in MVP** (paper says EM unreliable until ~Race 4; we have no ground truth). Honest limitation: HMM is analytically initialised, not trained on real data.

---

## 6. Data sources, config, acquisition

| Source | How to acquire | Use | Verdict |
|---|---|---|---|
| **FastF1** | `pip install fastf1`; `fastf1.Cache.enable_cache('./data/cache')`; `get_session(2026,'Melbourne','R')`; `s.laps`, `lap.get_car_data().add_distance()`, `get_circuit_info()` | Primary telemetry/timing | CORE |
| **OpenF1** | `requests` → `https://api.openf1.org/v1/{endpoint}?session_key=...&format=csv`; endpoints `laps, car_data, position, intervals, stints, pit, race_control, weather, drivers` | Gaps (~4 s), SC/VSC, stints, weather | CORE |
| **TUMFTM/racetrack-database** | `git clone https://github.com/TUMFTM/racetrack-database` | Segmentation (centreline/curvature) | CORE |
| **f1-circuits** (GeoJSON) | GitHub | Track map | CORE |
| **FIA PDFs** | `api.fia.com` PU Tech Regs; Sporting B Issue 08; Technical C Issue 20 (5 Aug 2026); event notes | `rules_2026.json` + event config | CORE |
| **Jolpica-F1 / Tracing Insights HF** | `api.jolpi.ca/ergast/f1/2026/...`; HF `tracinginsights/RaceData` | Standings / bulk fallback | NICE |
| **Nitrous devlog** | Read `nitrous.software/devlog` (Mar 2026) | Proof Energy Modes/Active Aero absent from API | INTEL |
| **arXiv:2603.01290** | `arxiv.org/abs/2603.01290` | Prior art (cite, do not copy) | CITE |

**NEVER available (never claim):** SoC, MGU-K power/torque, ERS mode, Active Aero state, fuel flow.

### Pre-cache list (do first)
**Melbourne 2026 R, Shanghai 2026 R, Bahrain 2026 R, Monza 2026 R, Baku 2026 R.**

### `config/rules_2026.json`
```json
{
  "regulation_issue": "Sporting B Issue 08 / Technical C Issue 20, published 5 Aug 2026",
  "post_miami_amendments": true,
  "soc_window_mj": 4.0,
  "harvest_cap_mj_per_lap": 9.0,
  "deploy_mj_per_lap": 8.5,
  "mgu_k_max_kw": 350,
  "power_to_propel_kw": "min(350, 1850 - 5*v_kph) if v_kph < 340 else 150",
  "zone_deploy_kw": {"key_acceleration": 350, "other": 250},
  "race_boost_cap_kw": 150,
  "superclip_max_kw": 350,
  "quali_recharge_mj": 7.0,
  "mgu_k_torque_nm": 500,
  "torque_efficiency_correction": 0.97,
  "start_min_speed_kph": 50,
  "pit_stationary_gain_kj": 100,
  "fuel_energy_flow_mj_per_h": 3000,
  "fuel_rpm_formula_below_10500": "0.27*N + 165",
  "non_ers_store_kj": 300,
  "slew_rate_kw_per_s": 100,
  "mguh_deleted": true,
  "detection_gap_s": 1.0,
  "overtake_bonus_mj": 0.5,
  "overtake_speed_kph": {"attacker_full": 337, "taper_zero": 355, "leader_taper_start": 290},
  "active_aero": {"proximity_gated": false, "transition_ms": 400, "disabled_after_start_until_turn1": true},
  "drs_deleted": true,
  "cars": 22,
  "teams": 11
}
```

### `config/event_shanghai.json` (from FIA note)
```json
{
  "event": "Shanghai", "year": 2026,
  "detection_line_m": 5130, "activation_line_m": 5250,
  "detection_gap_s": 1.0,
  "deploy_mj_with_overtake": 9.0, "deploy_mj_without_overtake": 8.5,
  "recharge_mj": 9.0,
  "max_power_reduction_kw_per_s": 100,
  "special_power_reduction_zones": [
    {"turns": "7-9", "start_m": 1950, "end_m": 2500},
    {"turns": "11-12", "start_m": 3100, "end_m": 3200}
  ],
  "overtake_zones": [], "active_aero_zones": []
}
```

### `config/event_bahrain.json` (template — verify from FIA note)
```json
{
  "event": "Bahrain", "year": 2026,
  "detection_line_m": 0, "activation_line_m": 0,
  "detection_gap_s": 1.0,
  "deploy_mj_with_overtake": 9.0, "deploy_mj_without_overtake": 8.5,
  "recharge_mj": 9.0,
  "max_power_reduction_kw_per_s": 100,
  "overtake_zones": [], "active_aero_zones": [],
  "brake_harvest_potential_mj": 0.0
}
```

### `config/ev_bus.json`
```json
{
  "vehicle": "electric bus",
  "battery_usable_window_kwh": 250,
  "reserve_soc_pct": 15,
  "regen_per_stop_kwh": 0.8,
  "traction_per_segment_kwh": 1.2,
  "max_power_kw": 250,
  "max_c_rate": 2.0,
  "stops_on_route": 20,
  "schedule_adherence_penalty": 1.0,
  "depot_charge_kw": 100
}
```

---

## 7. Validation (no ground-truth labels)

We cannot validate SoC directly. Validate by **predicting observables** + rule closure.

1. **Rule closure:** estimated SoC never exits `[0,4]` MJ; harvest/lap `≤9 MJ`; power respects rampdown/zone/boost/slew. Violation = bug. (In `test_soc_observer`.)
2. **Clipping prediction:** if observer says low SoC, the car **must** show end-of-straight speed deficit / flat speed at high throttle. Score precision/recall vs `ClippingDetector` on real telemetry.
   Real cases: **Bahrain T12** Alonso apex ~50 km/h lower than 2025, Leclerc & Norris flat through 300 m capped ~240 km/h; **Albert Park** Mercedes 327 km/h with later/smaller clipping vs Red Bull/Audi; **Spa** Norris vs Antonelli (+5 km/h Kemmel, +15 to Pouhon, +13 to Fagnes).
3. **Pass prediction:** label real 2026 overtakes from OpenF1 `position`; train LR; report **AUC** (target >0.7) + Brier.
4. **Multi-circuit ablation:** run policy on **Baku (~7.1 MJ)** vs **Monza (~3.3 MJ)**. Policy **must change** (more attack Baku, more harvest Monza). Proves physics response.
5. **Baseline comparison:** net race time / positions vs Greedy & Conservative. Report table.
6. **Honesty:** state no ground truth; cite Art.8.5 confidentiality, F1 removed SoC graphics, Nitrous devlog; watermark Estimated.

**Metrics:** clipping precision/recall, pass AUC, DP solve time, baseline delta, config sensitivity.

---

## 8. Real-world transfer

### PRIMARY: EV bus fleet (India, PM e-Bus Sewa)
| F1 2026 | EV bus |
|---|---|
| 4 MJ window | Battery usable window + mandated reserve |
| 9 MJ harvest cap | Regen recovery per stop/descent |
| ~8.5 MJ deploy/lap | Traction energy per route segment |
| 350 kW + rampdown | Max C-rate / power limit |
| Braking zones | Bus stops, descents |
| Overtake (+0.5 MJ, proximity) | Time-critical opportunity: recover schedule, clear signal, meet slot |
| Attack/Neutral/Harvest/Defend | Drive modes |
| Pit stop ≤100 kJ | Depot / opportunity charging |
| Finish above reserve | Reach depot above reserve |
| Repass / yo-yo | Schedule-slippage rebound |

**Same solver, different config file.** Claim: *"X% energy per trip saved at constant schedule adherence"* or *"Y% more trips per charge."*
**Secondary (one line):** microgrid dispatch (solar = harvest, evening peak = deploy).

Scalability kicker: Tier-1 DP **<10 ms** → runs on edge hardware in the vehicle, no cloud round-trip.

---

## 9. Citations & repos pack (proof by citation)

### Prior art (cite, do not copy)
**`arXiv:2603.01290`** — Kleisarchaki, *"Opponent State Inference Under Partial Observability: An HMM–POMDP Framework for 2026 Formula 1 Energy Strategy"*, 15 May 2026.
- Adopt: POMDP framing, `Lharvest/Lderate` split, counter-harvest trap, belief-state inference, `δthrottle`.
- Differentiate: we validate on **real 2026 replay** (paper is synthetic-only, valid from Race 4), add **compliance certificate**, use **DP+MPC not DQN**, include **Boost Mode**, update to **post-Miami / Aug-2026 rules**, add **EV-bus transfer**, watermark estimates.
- Cite as `arXiv:2603.01290v3 [cs.AI]`.

### FIA regulations (authoritative constants)
- PU Technical Regulations **Art. 5.4.1–5.4.13** (350 kW, `1850−5v` rampdown, 4 MJ ΔSoC, 9 MJ harvest, 500 Nm, 50 km/h start, 100 kJ pit, fuel flow). URL: `api.fia.com`
- Sporting **Section B Issue 08** (Art. **B7.1** Active Aero / Driver Adjustable Bodywork; **B7.2** Overtake Mode, event Detection Gap) + **Technical Section C Issue 20**, both **5 Aug 2026**
- FIA **race-director event notes** (Shanghai detection 5,130 m → activation 5,250 m; 9.0/8.5 MJ; 100 kW/s)

### "No public SoC/ERS" evidence
- **f1chronicle.com** "F1 Telemetry and Data" (6 Mar 2026): Art. 8.5 records SoC/MGU-K but *"the FIA keeps the data … confidential between teams."*
- **Nitrous devlog** "Trackmap Integration - March Update" (31 Mar 2026): *"Energy Modes … not yet available through the API"*; Active Aero *"not yet available in the data feed."*
- **Domenicali / F1 broadcast policy** (Jul 2026): F1 **removed** battery SoC graphics; CEO: *"no one is interested in how you drive your car."*

### Clipping is observable in public telemetry (validates observer)
- **planetf1.com** (15 Feb 2026): Bahrain T12 Alonso ~50 km/h apex deficit; Leclerc/Norris flat ~240 km/h (superclipping).
- **gptechnical.com** (9 Mar 2026): Mercedes 327 km/h Albert Park, later/smaller clipping vs Red Bull/Audi/Honda.
- **f1briefing.com** (1 Jul 2026): brake-only recovery **Baku 7.1 MJ, Monza 3.3 MJ, Melbourne 2.9 MJ**; superclipping costs top speed.
- **f1briefing.com** (22 Mar 2026): **Clipping-Claw** detected ERS clipping from throttle data and predicted Alonso's overtake **2 laps ahead**.
- **sportsnewsbreak.com** (17 Jul 2026): Spa Norris vs Antonelli deployment deltas.

### GitHub repos to use / cite
| Repo | Use |
|---|---|
| `theOehrly/Fast-F1` | Primary telemetry source |
| OpenF1 (`openf1.org`) | Gaps/positions/SC (no ERS endpoint) |
| `jolpica/jolpica-f1` | Historical results/standings |
| `TUMFTM/racetrack-database` | Lap segmentation geometry |
| `f1-circuits` (GeoJSON) | Track map |
| `mateenunez/f1-api-ws`, `ccc1236/f1-telemetry` (fork of `matteocelani`) | Optional live SignalR pipeline; proves no ERS channel |
| `TracingInsights-Archive` (HuggingFace) | Bulk offline fallback |
| `renumics/f1_dataset`, `formula1-datasets` (2019–2026) | Telemetry dataset structure / fallback |
| `LiveF1` (`GoktugOcal`) | Alternative ingest |
| `f1-dash` (sunset) | Reference only |
| `subinium/awesome-f1` | Ecosystem map / curated resources |
| Clipping-Claw (from f1briefing) | Prior art: clipping detectable from throttle/speed |
| F1 IntelliHub (Atharva Mandavkar) | FastF1 + TimescaleDB pipeline example |

**How to cite:** map each claim → one source (e.g. "no public ERS" → Nitrous devlog + f1chronicle; "clipping observable" → planetf1 + gptechnical + Clipping-Claw; "harvest circuit-limited" → f1briefing recovery numbers).

---

## 10. `f1-energy-dash.live` decision

**UI pattern only. Do NOT use its data or code.**
- **Take:** layout pattern — SoC bars for all drivers, three-state ERS mode indicators, driver comparison panel, timing tower with mini SoC bar, interactive track map, and **Scenario Mode** (pre-built narrative, e.g. Verstappen vs Norris at Albert Park).
- **Do NOT take:** its claimed real-time SoC/ERS data — **does not exist publicly** (proven by Nitrous devlog, Art. 8.5, F1 removal). It also shows an outdated grid and crypto payments.
- **Use:** rebuild those components in Streamlit with **our own estimated values** + watermark. Never scrape/subscribe/copy code.
- **Pitch line:** *"Our dashboard layout is inspired by second-screen energy dashboards, but every value is our own rule-constrained estimate from public telemetry — because no real battery feed is publicly available."*

---

## 11. Build plan & timeline (4 Sep – 13 Sep)

Organizer-approved **full pre-build** → build the whole project **now**. Sept 12–13 = final integration + rehearsal.

| Date | Work | Phase |
|---|---|---|
| **Sept 4 (today)** | Save this doc. Scaffold + `config/*.json`. Run `pre_cache.py` (5 races). Clone TUMFTM + f1-circuits. | 0 |
| **Sept 5** | Ingest (FastF1 + OpenF1) + segmentation + SoC observer + ERS + clipping. Test SoC in `[0,4]`, harvest ≤9 MJ. | 1–2 |
| **Sept 6** | Compliance ledger + Tier-1 DP + Pareto frontier. Test DP <10 ms, frontier monotonic, illegal rejected. | 3–4 |
| **Sept 7** | 8-state HMM + trap + Pass model (LR) + Overtake EV engine. Test GO/HOLD, trap flag. | 5 |
| **Sept 8** | Tier-2 MPC (scenario tree, 8–12 laps) + baselines (Greedy/Conservative replay). | 6, 8 |
| **Sept 9** | **Streamlit UI** exactly to §3 (minimalist, no emojis). Wire all modules. | 7 |
| **Sept 10** | EV-bus transfer + validation scripts (rule closure, clipping prediction, pass AUC, Baku-vs-Monza). | 9–10 |
| **Sept 11** | Full offline integration test. Record backup video. Freeze code. | — |
| **Sept 12** | Final integration, fix bugs, rehearse demo. | — |
| **Sept 13** | Pitch: narrative + live dashboard + EV-bus tab. Awards. | — |

**Fallback 24-h schedule (only if behind):** Day1 09-10 verify cache; 10-13 observer/ledger; 13-17 DP+EV; 17-20 UI; 20-24 baselines. Day2 00-04 MPC/trap/validation; 04-06 nap; 06-08 EV bus; 08-10 rehearse; 10-12 buffer + pitch.

**Commands:**
```
pytest -q
python scripts/pre_cache.py
python scripts/run_replay.py --event Melbourne
streamlit run src/raceiq/ui/main.py
```

---

## 12. WorkBuddy master instructions (non-negotiable)

1. **Do NOT** fetch/subscribe/copy code or reuse data from `f1-energy-dash.live`. UI layout only.
2. **Do NOT** use PyTorch/neural nets for SoC inference. SoC = deterministic physics observer. PyTorch only optional for pass classifier; prefer sklearn LR.
3. **Do NOT** use Monte Carlo Tree Search. Use scenario-tree MPC / rolling-horizon optimization.
4. **Do NOT** display SoC as "real". Always render **"Estimated"** with watermark.
5. **Do NOT** hard-code FIA constants. All from `config/rules_2026.json`.
6. **Offline-first.** Pre-cached FastF1 + downloaded OpenF1 + local track files. No paid live API.
7. **Streamlit** for UI (NOT React). Minimalist per §3. **No emojis.**
8. All code original; disclose libraries; cite `arXiv:2603.01290`; do not copy f1-energy-dash.
9. Type-hint + docstring all public functions. `pytest` ≥80% coverage on `inference/`, `rules/`, `optimize/`, `decision/`.
10. Organizer approved full pre-build → implement **all phases now (Sept 4–11)**.

**Repo structure:**
```
raceiq/
  README.md
  config/{rules_2026.json, event_bahrain.json, event_shanghai.json, ev_bus.json}
  data/{cache/, raw/openf1/, tracks/, processed/}
  src/raceiq/
    ingest/{fastf1_loader.py, openf1_client.py, cache_manager.py}
    track/segmentation.py
    inference/{soc_observer.py, ers_mode.py, clipping.py, opponent_belief.py}
    rules/ledger.py
    optimize/{tier1_dp.py, frontier.py, tier2_mpc.py}
    decision/{overtake_ev.py, pass_model.py}
    transfer/ev_bus.py
    ui/{main.py, components/}
    baselines/{greedy.py, conservative.py}
    validation/{validate_observer.py, validate_dp.py, metrics.py}
  tests/{test_ingest.py, test_soc_observer.py, test_ledger.py, test_tier1_dp.py, test_overtake_ev.py, test_ev_bus.py}
  scripts/{pre_cache.py, run_replay.py, run_validation.py}
```

**First instruction after reading:**
*"Create the full repository scaffold and Phase 0. Implement the config loader and config JSON files. Then implement Phase 1 ingest with FastF1 caching and OpenF1 download, plus pytest tests. Do not start Phase 2 until Phase 1 tests pass. Continue phase by phase."*

---

## 13. Acceptance criteria / Definition of Done

- `pytest` passes; ≥80% coverage on core modules.
- `scripts/pre_cache.py` caches **Melbourne + Shanghai + Bahrain (+ Monza/Baku)** offline.
- `streamlit run src/raceiq/ui/main.py` runs **offline** using cached session:
  - Timing tower **22 drivers**, mini **Estimated** SoC bars, mode chips (text, no emoji).
  - Track map animates driver dots on replay; Detection/Activation lines marked.
  - **Decision card** outputs `ATTACK/HOLD/HARVEST/DEFEND` + EV breakdown + trap banner.
  - **Compliance board** green/red PASS/FAIL for every rule in config.
  - Watermark present.
- `scripts/run_replay.py` prints net time/positions vs **Greedy** and **Conservative**.
- EV-bus module returns a drive-mode recommendation from `config/ev_bus.json`.
- README repeats the compliance watermark + prior-art citation.

---

## 14. Demo script & jury Q&A (rehearsal only — PPT still parked)

### Demo narrative (do NOT make slides yet)
1. **The paradox:** 4 MJ window, 11.4 s at 350 kW, cycles ~2×/lap. Harvest circuit-limited (Monza 3.3 vs Baku 7.1). SoC hidden.
2. **No SoC exists:** Art. 8.5 confidential; F1 removed graphics; Nitrous devlog "Energy Modes not yet available through API". So we built an **observer**.
3. **The engine:** 3 tiers — Tier-1 DP (<10 ms) → Tier-2 scenario MPC (8–12 laps) → priced Overtake bet. Compliance certificate.
4. **The bet (LIVE):** real 2026 race replay; detection line triggers; decision card shows `ATTACK` + EV breakdown (P(pass), repayment, repass, trap).
5. **Proof & transfer:** replay vs Greedy/Conservative; clipping validation on Bahrain/Spa; multi-circuit; EV-bus config; <10 ms edge.

### Q&A
- **"Where did you get battery data?"** → It does not exist publicly. We **infer** from public telemetry + rules and validate by predicting clipping/end-of-straight speed loss. All values watermarked Estimated.
- **"Why not deploy always?"** → 4 MJ drains in 11.4 s; harvest circuit-limited; spending now costs repayment laps; plus repass (yo-yo) risk.
- **"How do you know inference is right?"** → Rule closure + clipping prediction + pass AUC + Baku-vs-Monza ablation; we concede no ground truth.
- **"Isn't this the arXiv HMM paper?"** → We cite it as prior art. We adopt framing/trap, but improve: real-race validation, compliance certificate, MPC not DQN, EV-bus transfer, post-Miami rules, watermarked estimates.
- **"Rule compliance?"** → Compliance ledger checks every Art. 5.4.x + post-Miami + B7 rule; infeasible plan → EV = −∞. Board shown live.
- **"Real-life impact?"** → EV bus (PM e-Bus Sewa): same solver, config swap; X% energy/trip saved at constant schedule. Secondary microgrid.
- **"Prior building?"** → "Organizers approved full pre-build; written confirmation in Compliance section; all code original; libraries disclosed."
- **"Is the battery simulated?"** → No. The **race is a real replay**; the battery is **estimated/reconstructed**, not simulated. Simulation mode is separate and clearly labelled.

---

## 15. Compliance & organizer approval (fill before submission)

```
## Organizer pre-build approval (REQUIRED EVIDENCE)
- Event: TrackShift Innovation Challenge 2026, Plaksha University, 12–13 Sep 2026
- Problem: 1 — Energy & Overtake Intelligence
- Team: [Your team name], 2 members: [Name A], [Name B]
- Approval received from: [Organizer name], [Role], via [channel], on [date]
- Exact statement: "[paste exact words, e.g. 'Pre-working is allowed. You may complete the whole project before the finale.']"
- Evidence: [link to screenshot / email]

## Original work
All solution code in src/ is original. Libraries in requirements.txt and disclosed.
No code or data copied from f1-energy-dash.live; only UI layout imitated.

## Data honesty
No public ground-truth ERS/SoC telemetry. Every SoC, ERS mode and energy value in the UI is
ESTIMATED with a permanent watermark. We never claim the numbers are official or broadcast data.

## Prior art
Cited arXiv:2603.01290 as prior art and differentiated. No implementation copied.

## Event rules honoured
No paid live feeds required; all FIA values in config JSON; real-world impact module included.
```

---

### Final note
Start **Phase 0 today**: create the scaffold, write the four `config/*.json` files, and run `pre_cache.py`. Feed this document to WorkBuddy and proceed phase by phase. **Do not ask for PPT** — after the build completes (~Sept 11–12), send me the shipped modules, demo circuits, baseline numbers vs Greedy/Conservative, validation result (clipping precision/recall + pass AUC), and whether EV-bus shipped, and I will then produce the final deck.
