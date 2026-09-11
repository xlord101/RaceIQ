# RaceIQ 2026 — Codebase Reference

**Purpose of this document.** This is the authoritative file-by-file map of the
RaceIQ 2026 repository, written so that *any other model or engineer* can pick up
the project cold and continue work. It complements `README.md` (project status,
build checklist, validation results) and `FRONTEND_BRIEF.md` (the animated-frontend
contract + the Antigravity prompt). Where those docs overstate or are stale, this
file states the **actual** state of the code.

Repo: `C:/Dev-Drive/Trackshift_RaceIQ` · Challenge: TrackShift 2026, Problem 1
(Energy & Overtake Intelligence) · Team framing: **RaceIQ = the Haas F1 Team pit wall**.

---

## 0. The one rule that governs everything

> **Every energy / SoC number in this repo is an ESTIMATE.** No public ERS/SoC
> telemetry exists. The SoC is inferred by a **deterministic physics observer**
> from public channels (speed, throttle, brake, gear) plus the FIA rule
> stack. It is never presented as measured.

Consequences baked into the architecture:

- The UI watermark is mandatory: *"Estimated SoC – inferred from public telemetry
  + FIA rules. No public ERS/SoC telemetry exists."*
- No PyTorch / neural nets anywhere for SoC — only a physics observer.
- No hard-coded FIA constants — every regulation value lives in `config/*.json`
  and is read through `src/raceiq/config.py`.
- Data provenance is explicit. Real cached telemetry, downloaded OpenF1, and
  synthetically-generated fallback are each labelled and never conflated.

**Honesty reconciliation (important):** An earlier draft claimed RaceIQ "won all 5
grids / all 5 circuits." That was inaccurate. The true data state is in §6: only
**Melbourne, Shanghai, Monza** have real 2026 FastF1 telemetry. **Bahrain** has
no FastF1 telemetry, and **Baku** was not raced in 2026 (`simulation_only: true`).
For those two, grids and replays use a *canonical-lineup fallback* and a
*physics-placeholder frontier* and are flagged as such. `README.md` §5's "all five
win" table is produced by `scripts/run_replay.py`, which now prints a loud
`!! WARNING: NO REAL TELEMETRY ... NOT evidence` line for the synthetic circuits.
Do not repeat the "all 5" claim as ground truth.

---

## 1. Tech stack & environment

| Concern | Choice |
|---|---|
| Language | Python 3.10+ (built & tested on 3.13) |
| Numerics | numpy, pandas |
| ML (only `P(pass)`) | scikit-learn `LogisticRegression` + isotonic calibration |
| Telemetry | FastF1 (cached, offline-first), OpenF1 (downloaded CSV) |
| Spec-mandated UI | Streamlit (`src/raceiq/ui/main.py`) |
| Showpiece UI | React + Vite + TypeScript (separate `frontend/`, fed JSON) |
| Charts | Plotly |
| Tests | pytest (`tests/`), coverage gate on 4 packages |
| Package layout | `src/` layout (`packages.find` where=`src`) |

**Running Python:** use the managed interpreter, not the bare `python` on PATH.
The working test invocation used in this build:

```bash
PYTHONPATH=src C:/Users/rugve/.workbuddy-ai/binaries/python/envs/default/Scripts/python.exe -m pytest -p no:cacheprovider -q
```

A full run exceeds the default timeout; pass an extended timeout (or run in the
background). The `pytest.ini` (`pyproject.toml [tool.pytest.ini_options]`) sets
`pythonpath = ["src"]`, `testpaths = ["tests"]`, `--strict-markers`.

---

## 2. Repository layout

```
config/       rules_2026.json  event_shanghai.json  event_bahrain.json
              circuits.json    ev_bus.json          hmm_priors.json
data/         cache_manifest.json
              grid_<circuit>_{real,battle,battle_trap}.json  (5×3 = 15)
              sample_scenario{,_trap}.json                    (2)
              racecast_{melbourne,shanghai,monza}.json        (3)
              cache/ raw/ processed/ tracks/                  (offline data dirs)
src/raceiq/   config.py  physics.py  pipeline.py  types.py  __init__.py
  ingest/     cache_manager.py  fastf1_loader.py  openf1_client.py
  track/      segmentation.py
  inference/  soc_observer.py  ers_mode.py  clipping.py  opponent_belief.py
  rules/      ledger.py
  optimize/   frontier.py  tier1_dp.py  tier2_mpc.py
  decision/   pass_model.py  overtake_ev.py
  transfer/   ev_bus.py
  baselines/  greedy.py  conservative.py  race_sim.py  compare.py
  validation/ metrics.py
  ui/         main.py  scenario.py  contract.py  grid.py  racecast.py
scripts/      pre_cache.py  run_replay.py  run_validation.py
              _bench*.py _dbg_dp.py _prof_dp.py _smoke_dp.py   (dev micro-benchmarks)
tests/        18 test modules (see §9)
frontend/     React+Vite app (the animated showpiece; built from JSON fixtures)
```

---

## 3. Architecture & data flow

The pipeline is a strict **layered** flow. Dependencies point downward; the UI and
validation layers consume the outputs of everything above them. Circular imports
are avoided by keeping all shared shapes in `types.py`.

```
              config/*.json ──► config.py (typed loaders)
                                      │
telemetry ─► ingest/ ──(segments)──► track/segmentation.py
   │                                      │
   │                                      ▼
   └──► inference/ ◄── physics.py ──► optimize/ (tier1_dp, frontier, tier2_mpc)
            │  │  │                          │
            │  │  └─ opponent_belief (HMM)   │
            │  └─ ers_mode / clipping        │
            └─ soc_observer (est. SoC)       │
                         │                   │
                         ▼                   ▼
                   rules/ledger.py ──► decision/ (pass_model → overtake_ev)
                                              │
                          ┌───────────────────┴──────────────┐
                          ▼                                  ▼
                  baselines/ (compare)              ui/ (scenario, contract,
                          │                          grid, racecast → main / JSON)
                          ▼                                  │
                  validation/metrics.py ◄───────────────────┘
```

**Per-lap decision chain (the "working" a judge sees):**
1. `track/segmentation` cuts a lap into typed segments (brake/exit/straight/coast).
2. `optimize/tier1_dp.solve_lap_dp` produces the **Pareto frontier** = the price
   list of joules↔seconds for that lap (runs < 10 ms).
3. `inference/soc_observer` estimates each car's SoC trajectory (ESTIMATED).
4. `inference/opponent_belief` runs the 8-state HMM → rival ERS state + trap flag.
5. `decision/pass_model` gives `P(pass)`; `decision/overtake_ev` prices the bet
   `EV = P(pass)·points − repass − repayment − λ·illegal` → `GO`/`HOLD`.
6. `optimize/tier2_mpc` sets the stint posture (`ATTACK/NEUTRAL/HARVEST/DEFEND`).

`ui/contract._working` exposes this whole chain as plain numbers so nothing is a
black box.

---

## 4. Configuration files (`config/`)

All regulation numbers live here. `config.py` reads them; nothing in `src/` hard-codes an FIA constant.

| File | Contents / key fields | Notes |
|---|---|---|
| `rules_2026.json` | `soc_window_mj` (4), `harvest_cap_mj_per_lap` (9), `deploy_mj_per_lap` (8.5), `mgu_k_max_kw` (350), `race_boost_cap_kw`, `base_deploy_kw`, `superclip_max_kw`, `overtake_bonus_mj` (0.5), `zone_deploy_kw`, `start_min_speed_kph`, `pit_stationary_gain_kj`, `slew_rate_kw_per_s`, `power_to_propel_params`, `fuel_rpm_params`, `physics` (vehicle model assumptions), `dp` (DP binning/actions), `points` (FIA points table). | Keys starting with `_` (e.g. `_comment`, `_verified`) are stripped by `config._clean()`. |
| `event_shanghai.json` / `event_bahrain.json` | `detection_line_m`, `activation_line_m` (may be `null`/unconfirmed), `detection_gap_s`, `deploy_mj_with_overtake`/`_without_overtake`, `recharge_mj`, aero/active-aero zones, `_verified`. | Shanghai is verified; Bahrain is an unverified template. |
| `circuits.json` | `circuits{}` (per-circuit `lap_length_m`, `corners`, `brake_harvest_potential_mj`, `data_status`, `simulation_only`, `openf1_session_key`, `fastf1_event`), plus `demo_order` and `ablation_pair`. | `demo_order = [Melbourne, Shanghai, Monza, Bahrain, Baku]`. `ablation_pair = [Monza, Baku]`. |
| `ev_bus.json` | Battery-bus transfer config: `battery_usable_window_kwh`, `reserve_soc_pct`, `regen_per_stop_kwh`, `max_power_kw`, `stops_on_route`, `route`, `solver`, `modes`. | Used only by `transfer/ev_bus.py`. |
| `hmm_priors.json` | 8-state HMM priors: `states`, `ers_states` (H/M/Lharvest/Lderate), `initial`, `transitions`, `emissions`, `trap`. | Analytic, **untrained** — no fitting. |

**Config data-status values (provenance):**
`cached_2026` (real telemetry present) · `no_fastf1_telemetry` (fallback) ·
`not_raced_yet_2026` (`simulation_only: true`).

---

## 5. Core modules

### `src/raceiq/config.py` (517 lines)
Typed loaders over `config/*.json`. Classes: `ConfigError`, `RulesConfig`,
`EventConfig`, `EvBusConfig`, `CircuitConfig`, `HMMConfig`. Functions:
`config_dir()` (honours `RACEIQ_CONFIG_DIR`), `load_rules/load_event/load_ev_bus/
load_circuits/load_hmm_priors/list_events`. Helpers `power_to_propel_kw(speed,
rules)` (Art. 5.4.5 ramp-down) and `fuel_flow_limit_kg_per_h(rpm, rules)`.
Configs are cached in a module-level dict guarded by an `RLock`. Every value the
rest of the code uses comes from here — **do not add a literal FIA number anywhere
else.**

### `src/raceiq/physics.py` (166 lines)
Deterministic vehicle physics. **No NN.** Functions: `brake_energy_mj`,
`harvest_energy_mj` (MGU-K-only; no MGU-H), `drag_power_kw`, `segment_duration_s`,
`steady_state_speed_gain` (nonlinear drag solve — bounded, never +70 m/s),
`deploy_gain(power, base_time, speed, length, phys, horizon_s)` returning
`(time_saved_s, battery_mj)` with the acceleration-phase carry-over that makes
energy on a straight pay off down its whole length, and `superclip_penalty_s`.
All parameters are passed in from `RulesConfig.physics`.

### `src/raceiq/types.py` (313 lines)
Shared, frozen dataclasses so modules never import each other circularly:
- `Segment` — one discretised lap slice (`kind ∈ brake/exit/straight/coast`, speeds, `harvest_potential_mj`, `is_key_acceleration`).
- `SocState` — **estimated** SoC for one sample (`soc_mj`, `mode`, `clipping_flag`, `soc_pct`); `from_soc()` factory.
- `Belief` — 8-state HMM posterior: `probs[8]`, `p_ers{}`, `p_overtake_available`, `trap_prob`, `trap_flag`, `evidence`; accessors `p_Lharvest`, `p_Lderate`, `dominant_ers`.
- `PlanSegment` / `DeploymentPlan` (with `deploy_mj/harvest_mj/net_mj/peak_power_kw`).
- `ComplianceResult` (`passed`, `violations`, `as_rows()`).
- `Posture` (Tier-2 output), `OvertakeDecision` (`go`, `recommendation`, `p_pass`, `ev`, `trap_flag`, `eligible`, `as_dict()`), `BusRecommendation`.

### `src/raceiq/pipeline.py` (481 lines)
End-to-end replay: session → segments → estimated SoC field. `ReplaySession`
exposes `timing_tower`, `soc_at_lap`, `speed_trace`, `soc_history`, etc.
`build_replay(event, year, session, rules, cache_dir, drivers, max_laps)` is the
entry point. `_project_single_lap` / `_project_race` integrate SoC from a
per-segment net-energy profile. **Coverage is ~53% — below the gate** (tested via
integration paths, not unit tests). Not a blocker, but treat edits here carefully.

---

## 6. Layer reference (src/raceiq)

### `ingest/` — data loading (offline-first)
- **`cache_manager.py`** — Filesystem layout + manifest. `data_dir()/cache_dir()/
  raw_dir()/tracks_dir()/processed_dir()` (honour `RACEIQ_DATA_DIR`),
  `read_manifest/write_manifest`, `cache_status()`, `_count_telemetry_samples`,
  `pre_cache_sessions(events, ...)` (reports failures without raising).
- **`fastf1_loader.py`** — `SessionData` (driver/team/number, telemetry access),
  `load_fastf1_session(...)`, `get_lap_telemetry(data, driver, lap, resample_m)`,
  `_resample_by_distance` (uniform distance grid), `list_cached_events()`. Has an
  OpenF1 fallback path (`_openf1_telemetry`) when FastF1 cache is absent.
- **`openf1_client.py`** — `fetch_openf1` (returns empty frame on network error —
  never raises), `download_session` (persist CSVs), `load_openf1_local` (offline),
  `session_key_for(year, event)` (resolved from `circuits.json`, no network).
- **Provenance:** telemetry is real only where `cache/` and `raw/` hold it
  (Melbourne/Shanghai/Monza/Spa). Bahrain/Baku fall back to canonical lineup.

### `track/segmentation.py` — lap geometry
`TrackGeometry`, `geometry_from_circuit_info`, `_classify` (speed-trace label),
`build_segments(track_geo, speed_trace, rules, step_m)`,
`mark_key_acceleration_zones` (flags longest full-throttle runs as 350 kW zones),
`longest_straight`, `segments_from_telemetry` (convenience wrapper),
`segments_to_frame`, `max_legal_deploy_kw(speed, segment, rules)`. Emits
`types.Segment` objects consumed by the observer and the DP.

### `inference/` — estimating what nobody publishes
- **`soc_observer.py`** (631 lines — the largest, most important module).
  `SocObserver`: deterministic, rule-clamped energy-balance observer. Key design:
  `duty` = driver **demand** (aggression-driven, defaults to full request) is
  **separate** from `sustainable_duty` = the energy-neutral budget used by the
  planner. This split is what lets the observer actually *raise* a clipping flag.
  `fit_duty_to_observed()` bisects the demand duty to match the clipping rate
  *visible in real telemetry* (`predicted_observable_clip_frac`). `observe_field()`
  runs the observer for all ~22 cars cheaply. `LapObservation` aggregates one lap.
- **`ers_mode.py`** — `ErsClassifier.classify` → Harvest/Balance/Deploy (rule-based, text chips).
- **`clipping.py`** — `ClippingDetector` (stateful), `clipping_flags` (vectorised),
  `clipping_summary`, `clipping_events` (contiguous runs). Conservative by design
  (precision 1.0, recall ~0.77) — a false "we are clipping" costs real strategy.
- **`opponent_belief.py`** — `OpponentBelief`: recursive Bayesian filter over the
  8 hidden states (`ERS ∈ {H,M,Lharvest,Lderate} × Overtake ∈ {available,spent}`),
  **analytic forward algorithm, no training**. `compute_emissions()` derives
  emission likelihoods from public telemetry; `_trap()` raises `trap_flag` when the
  rival conserves in an aero zone (the counter-harvest trap). `batch()` for sequences.

### `rules/ledger.py` — FIA compliance
`ComplianceLedger` checks candidate plans against **9 rules** driven entirely by
`rules_2026.json` (SoC window, harvest cap, deploy cap, power-to-propel, boost cap,
start-speed rule lap-1 only, pit gain, torque, slew rate). `check()` returns
`ComplianceResult` (AND of rules; rejects, does not soft-score). `certificate_text()`
renders the plain-text certificate. `board_rows()` feeds the UI.

### `optimize/` — the price of energy
- **`frontier.py`** — `ParetoFrontier`: non-dominated (energy, lap-time) points;
  `is_monotonic`, `time_for_energy`, `energy_for_time`, `exchange_rate`,
  `marginal_rate`, `as_frame`, `to_dict`. The "price list" for one lap.
- **`tier1_dp.py`** (583 lines) — `solve_lap_dp(segments, config, soc_bins,
  start_soc_frac, return_plan, program)` — the single-lap energy/time DP, spec
  target **< 10 ms**. `precompile()` builds (and caches) per-segment shift tables
  (`_Program`, `_Stage`) outside the timed loop. `Tier1DP` is the object wrapper.
  `solve_lap_dp_full` adds timing instrumentation.
  **CRITICAL UNITS NOTE:** `solve_lap_dp` returns **time saved vs a no-ERS
  baseline** (negative = faster, e.g. −2.04 s). A physics *placeholder* frontier
  returns **absolute lap times** (~92 s). Summing deltas as if absolute = nonsense.
  `run_replay.py` detects this and labels the column `DeltaT(s)`. A new model
  adding a frontier consumer MUST respect this sign convention.
- **`tier2_mpc.py`** — `Tier2MPC.recommend(MPCState)` over the Tier-1 frontier,
  scenario-tree, 8–12 lap horizon, postures `ATTACK/NEUTRAL/HARVEST/DEFEND`,
  `DEFEND` when low SoC, `HOLD`/no-attack on trap. **No MCTS.**

### `decision/` — the priced bet
- **`pass_model.py`** — `PassModel`: calibrated `sklearn.LogisticRegression` +
  isotonic. `trained()` flag; before fitting it uses `heuristic_p_pass()`
  (deterministic, dynamic range verified by regression tests). **12-feature** vector
  (`_as_feature_row` fixes the order). Intercept was deliberately changed
  `2.2 → −1.5` so the reference case lands near 0.80, not 0.99.
- **`overtake_ev.py`** — `OvertakeEV.evaluate(OvertakeContext)` →
  `OvertakeDecision`. `EV = P(pass)·points_gain − repass_risk − repayment − λ·illegal`.
  `GO` iff `EV > 0 AND eligible AND legal AND NOT trap`. Exposes full `breakdown_*`
  fields and a human-readable `why`.

### `transfer/ev_bus.py` — domain transfer (Phase 9)
`EVBusSolver.recommend(BusState)` — the **same** energy logic, different config
(`ev_bus.json`): 4 MJ window → bus battery usable window + mandated reserve;
braking zones → bus stops; Overtake Mode → time-critical schedule recovery.
`BusRecommendation` carries the drive mode + projected SoC.

### `baselines/` — comparison strategies
- **`greedy.py`** — `GreedyStrategy`: max deploy whenever rival within Detection Gap.
- **`conservative.py`** — `ConservativeStrategy`: save late, never attack.
- **`race_sim.py`** — `RaceSimulator.simulate(strategy, rival_model)` rolls a race
  forward; `SimResult.total_time_s`. `Strategy` is a Protocol returning target net
  energy [MJ] per lap.
- **`compare.py`** — `compare(frontier, config, event, laps, initial_soc_mj, ...)`
  runs all three and ranks by time; `Comparison.as_rows()`. `RaceIQStrategy` drives
  the Tier-2 MPC posture.

### `validation/metrics.py` — spec §7 (validate without ground truth)
Six checks, all driven by `run_all()`:
1. `rule_closure_check` — estimates never break the FIA stack.
2. `clipping_precision_recall` — recover a *known injected* clipping region.
3. `pass_auc` — AUC/Brier on a synthetic known-logit dataset (target AUC > 0.70).
4. `circuit_ablation` — hold frontier fixed, vary harvest (Baku vs Monza) → policy changes.
5. `baseline_report` — RaceIQ beats both baselines on time.
6. `observer_calibration_check` — fit demand duty to *observable* clipping on real telemetry (skips gracefully if no cache).

`physics_frontier` / `synthetic_lap_telemetry` are deterministic helpers.

---

## 7. UI layer (`src/raceiq/ui/`)

Three roles: (a) the **spec-mandated Streamlit app** (`main.py`); (b) the
**Streamlit-free data builders** (`scenario.py`, `grid.py`) that produce the JSON
contract; (c) the **frontend contract + fixtures** (`contract.py`, `racecast.py`).

### `grid.py` (472 lines) — **we are Haas**
`OUR_TEAM = "Haas F1 Team"`, `OUR_DRIVERS = ("OCO","BEA")` (OCO #31, BEA #87),
`DEMO_CIRCUITS` = the five. `CANONICAL_LINEUP` = the real 2026 entry list (Verstappen,
Norris, Leclerc, Hamilton, Alonso, the two Haas cars, etc.) with **real teams**
(Audi, Racing Bulls, Cadillac), colours, car numbers — *not* placeholders.
- `load_lineup(circuit)` → real drivers from cached FastF1 `driver_info`.
- `real_pace(circuit)` → median lap times from `timing_app_data`.
- `build_grid(circuit, lap, pace)` → order = real pace ranking; gaps = pace deficit × laps (clamped 0.15–4.0 s). Falls back to canonical entry order + realistic spread when no telemetry, and **flags** it.
- `apply_edits(grid, order, gap_overrides)` → edited grid (`edited=True`) — this is what prices the live bet.
- `our_cars(grid)` (the Haas pair), `circuit_status(circuit)` (`data_status`, `simulation_only`).

### `scenario.py` (452 lines) — one UI frame
`build_scenario(event, lap, total_laps, ego_index, harvest_mj, trap, seed, rules,
our_team, focus, grid, focus_gap)` → `Scenario`. `_build_tower()` uses the **real**
`Grid` (order/gaps real; only SoC estimated). `_rival_belief()` runs the HMM.
`_compliance()` certifies the **Tier-1 DP** plan. `focus_gap` turns a static grid
into a live bet; `trap` arms the counter-harvest trap (→ HOLD). `DriverRow` is one
timing-tower row. The `Scenario` is deterministic per `seed`.

### `contract.py` (290 lines) — the JSON contract
`scenario_to_frontend(scenario)` projects a `Scenario` to the flat JSON the
frontend consumes (see `FRONTEND_BRIEF.md` §2 for the full key list: `meta`,
`grid`, `tower`, `belief`, `decision`, `posture`, `compliance`, `frontier`,
`comparison`, `soc_history`, `speed_trace`). `_working(scenario)` exposes the
**entire calculation chain** (`chain[6]`, `ev_formula`, `ev_terms`, `decision_rule`,
`eligibility`, `trap_test`, `price_of_energy`, `battery_estimate`,
`compliance_measured`) — the "show your working" panel. `write_sample()` regenerates
the **17 fixtures** (5 circuits × {real, battle, battle_trap} + `sample_scenario{,_trap}.json`).
Run with: `PYTHONPATH=src python src/raceiq/ui/contract.py`.

### `racecast.py` (419 lines) — full-race simulation (main view)
`build_racecast(circuit, total_laps, seed, rules, frontier)` → `RaceCast` with
`laps[]`, each `LapFrame` = `cars[22]` (`CarFrame`: SoC/mode/speed/throttle/brake/
clipping/lap_time) + `haas[2]` (`HaasFrame`: action/go/eligible/p_pass/ev/reward_pts/
risk_pts/risk_reward/trap_flag/rationale). Energy model is balanced:
`deploy = min(harvest * k, deploy_mj_per_lap)` with `k = 0.78 + aggression*0.42`,
so SoC stays inside the 4 MJ window and spreads 18%–100% across the field (a
regression fix — an earlier model drained every car to 0%). `write_racecast()`
writes `racecast_<circuit>.json`. **Fixtures exist only for Melbourne/Shanghai/Monza**
(the real-telemetry circuits). Regenerate:
`PYTHONPATH=src python -c "from raceiq.ui import racecast; racecast.write_racecast('data', ['Melbourne','Shanghai','Monza'], 7)"`.

### `main.py` (516 lines) — Streamlit pit wall (spec §3.4)
Three tabs: **REPLAY** (`_tab_replay`), **SIMULATION** (`_tab_simulation`),
**EV BUS** (`_tab_ev_bus`). Renderers: `_timing_tower` (22 drivers, monotonic
intervals, estimated-SoC bars), `_track_map` (detection/activation lines),
`_decision_card` (GO/HOLD + EV breakdown + why + trap banner), `_driver_compare`,
`_compliance_board` (PASS/FAIL per rule), `_chart_soc/_chart_speed/_chart_delta`,
watermark on every frame. `_chart()` probes the `st.plotly_chart` signature
(`use_container_width` → `width` in Streamlit 1.50+) for version tolerance.
`_inject_css()` uses `string.Template` (literal `%`/`{}` in CSS would otherwise
corrupt placeholders). Tests use Streamlit `AppTest` (`tests/test_ui_app.py`) — the
sandbox proxy returns 502 for live `curl`, so rely on `AppTest`, not a running server.

---

## 8. Scripts (`scripts/`)

| Script | What it does |
|---|---|
| `pre_cache.py` | Pre-caches every demo race (FastF1 + OpenF1) so the pipeline runs offline. Run once with network. |
| `run_replay.py` | Offline replay vs Greedy & Conservative. `_real_frontier(event, harvest)` builds the frontier from **real** cached telemetry via `load_fastf1_session → get_lap_telemetry → segments_from_telemetry → solve_lap_dp`; `_physics_frontier()` is the defensible placeholder. Prints `!! WARNING: NO REAL TELEMETRY ... NOT evidence` for synthetic circuits. **Earlier bug fixed here:** a swallowed `ImportError` made every circuit report "cached Tier-1 DP" on placeholder data. |
| `run_validation.py` | Calls `validation.metrics.run_all`, prints the 6-section report, exits 0/1. |
| `_bench*.py`, `_dbg_dp.py`, `_prof_dp.py`, `_smoke_dp.py` | Developer micro-benchmarks for the Tier-1 DP (timing, quantisation, float32). **Not part of the build** — do not ship or test these. |

---

## 9. Tests (`tests/`)

~210 tests, all passing in isolation. **Coverage gate (≥ 80%) applies to
`inference/`, `rules/`, `optimize/`, `decision/` — all pass.** `pipeline.py` (53%)
and `ingest/*` (~70%) are exercised via integration paths and are explicitly below
the gate (non-blocking).

| Module | Covers |
|---|---|
| `conftest.py` | Fixtures: `rules`, `synthetic_segments`, `cached_events`, `replay`, `real_segments`. `@needs_cache` markers skip network/cache-dependent tests cleanly. |
| `test_config.py` | Config loading + FIA constant derivation; missing-config raises. |
| `test_ingest.py` | Cache dirs, offline OpenF1 degradation (empty frame, no raise), manifest round-trip, pre-cache reports failure. |
| `test_soc_observer.py` | Physics bounds, harvest cap, SoC window; the `duty` vs `sustainable_duty` split; `fit_duty_to_observed` convergence; observable-clip mask. |
| `test_clipping.py` | Detector persistence/reset; precision/recall vs injected region (25 trials). |
| `test_ledger.py` | All 9 rules; "rejecting not scoring"; DP plan clears the ledger. |
| `test_tier1_dp.py` | Frontier monotonicity, legal actions, `< 10 ms`, SoC window, real-circuit solve. |
| `test_tier2_mpc.py` | Posture validity, Baku-vs-Monza ablation, low-SoC protects, trap blocks attack. |
| `test_opponent_belief.py` | Prior sums to 1, HMM update, trap path triggers on aero-zone conserving emissions. |
| `test_overtake_ev.py` | GO/HOLD semantics, trap→HOLD, illegal→HOLD, repayment higher on low-harvest circuit, heuristic calibration regression. |
| `test_baselines.py` | Greedy attacks more, Conservative preserves SoC, RaceIQ valid + beats baselines in pack. |
| `test_ev_bus.py` | Bus solver: charge protection, schedule recovery, reserve monotonicity, descent regen. |
| `test_validation.py` | The five spec-§7 checks + observer calibration runs-or-skips. |
| `test_scenario.py` | Full UI contract: 22-row tower, monotonic intervals, real grid honest, focus_gap makes bet live, Haas framing, trap flips to HOLD, no emoji, watermark present. |
| `test_contract.py` | JSON contract keys, belief shape, grid completeness/order, `working` reconciles EV, Baku flagged simulation. |
| `test_grid.py` | Canonical lineup is a full 2026 field, Haas has 2 cars, real circuits use real pace, Bahrain/Baku fallback + flagged, apply_edits reorders + flags. |
| `test_racecast.py` | One frame/lap, 22 cars, Haas pinned, SoC in-window + spreads, positions change, priced bet, risk/reward consistency, JSON-serialisable, hover telemetry. |
| `test_ui_app.py` | Streamlit `AppTest`: app runs, 3 tabs, charts render, CSS substituted, no emoji, watermark, trap→HOLD, EV-bus tab. |

**Known flake (unfixed, unrelated to UI):** `test_tier1_dp.py::
test_dp_under_10ms_on_real_circuit` has a median ~16 ms under full-suite load but
passes < 10 ms in isolation. The DP is correct; it is a CI-timing artifact.

---

## 10. Generated data artifacts (`data/`)

| Artifact | Generated by | Provenance |
|---|---|---|
| `grid_<circuit>_{real,battle,battle_trap}.json` (15) | `contract.write_sample` | `real` = untouched real grid; `battle` = Haas inside Detection Gap (live bet); `battle_trap` = +counter-harvest trap (→ HOLD). |
| `sample_scenario{,_trap}.json` (2) | `contract.write_sample` | Melbourne headline GO / HOLD frames. |
| `racecast_{melbourne,shanghai,monza}.json` (3) | `racecast.write_racecast` | Full-race replay, 22 cars/lap + pinned Haas pair. Real-telemetry circuits only. |
| `cache_manifest.json` | `cache_manager` | Records which circuits/sessions are cached. |
| `cache/ raw/ processed/ tracks/` | `pre_cache.py` | Offline FastF1 cache, downloaded OpenF1 CSVs, derived artefacts, local track geometry. |

---

## 11. Frontend (`frontend/`)

A separate **React + Vite + TypeScript** app (the animated showpiece). It does
**no physics** — it only renders the JSON fixtures from §10. Stack:
React 19, Framer Motion (card/panel motion), `requestAnimationFrame` circuit loop,
Canvas 2D / SVG track, Tailwind, lucide-react icons. Entry: `src/main.tsx`,
root `src/App.tsx`, types `src/types.ts`, styles `src/App.css`/`src/index.css`.

The exact brief + the **final consolidated Antigravity prompt** live in
`FRONTEND_BRIEF.md` §3b. Key requirements it encodes:
- **Racecast is the main view** — replay a previous race, all 22 cars moving on a
  loop, hover any car for telemetry, pin the two Haas cars with live risk/reward
  ratio + action button, lap scrubber.
- **Dark broadcast aesthetic**, no emojis, watermark + `arXiv:2603.01290` always visible.
- **Honesty badges**: `SIMULATION` (Baku), `GRID EDITED`, `SYNTHETIC — NOT EVIDENCE`.
- Grid editor: numeric focus-car gap → swaps to `*_battle*` fixtures; TRAP toggle →
  `*_battle_trap`.
- "THE CALL, PRICED" panel from `working` proves the EV is not a guess.

The frontend is intentionally **outside `src/`** so the Python package stays
spec-compliant and testable; it is the demo surface, not the deliverable core.

---

## 12. Common tasks (hand-off checklist)

```bash
# 1. Install
pip install -r requirements.txt

# 2. Pre-cache telemetry (needs network once; otherwise uses cached/raw/)
PYTHONPATH=src python scripts/pre_cache.py

# 3. Regenerate the 17 JSON fixtures
PYTHONPATH=src python src/raceiq/ui/contract.py

# 4. Regenerate the 3 racecast fixtures
PYTHONPATH=src python -c "from raceiq.ui import racecast; racecast.write_racecast('data', ['Melbourne','Shanghai','Monza'], 7)"

# 5. Run the spec-mandated Streamlit app
streamlit run src/raceiq/ui/main.py

# 6. Headless replay (prints warning for synthetic circuits)
PYTHONPATH=src python scripts/run_replay.py --event Melbourne

# 7. Full validation report (exit 0/1)
PYTHONPATH=src python scripts/run_validation.py

# 8. Tests (use managed interpreter; extended timeout for full run)
PYTHONPATH=src <managed-python> -m pytest -p no:cacheprovider -q
```

---

## 13. Gotchas for the next model

1. **SoC is always ESTIMATED.** Never label it measured. Keep the watermark.
2. **Tier-1 DP returns time *saved* (negative = faster), not absolute lap time.**
   The placeholder frontier returns absolute. Don't mix them (the replay handles
   this with a `DeltaT(s)` label).
3. **No hard-coded FIA numbers.** Add regulation values to `config/rules_2026.json`
   and read them via `config.py`.
4. **No PyTorch/NN for SoC; no MCTS for the MPC.** Deterministic observer +
   scenario-tree MPC only.
5. **Haas framing is load-bearing.** `meta.our_team = "Haas F1 Team"`,
   cars OCO/BEA. Never present a generic "P3".
6. **Honesty over polish.** Synthetic/simulated/edited frames carry badges and
   `data_status`. Do not present them as evidence. The "all 5 win" phrasing in
   `README.md` §5 is overstated — 3 circuits are on real telemetry, 2 are synthetic.
7. **`pipeline.py` and `ingest/*` are below the coverage gate.** Edit with care;
   they are integration-tested, not unit-tested.
8. **`test_tier1_dp` timing test is a known flake** under load — not a real failure.
9. **Streamlit app tests use `AppTest`**, not a live server (sandbox proxy 502s).
10. **`_bench*_dp.py` etc. are dev scratch** — ignore them for the build.

---

*Generated as the project hand-off reference. Cross-check against `README.md`
(status/validation) and `FRONTEND_BRIEF.md` (UI contract + prompt). Where they
disagree, this file and the actual `src/` code win.*
