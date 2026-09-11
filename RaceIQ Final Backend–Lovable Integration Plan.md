# RACEIQ — FINAL BACKEND + LOVABLE INTEGRATION

## ROLE

You are now working directly inside the actual RaceIQ repository.

Repository:

`https://github.com/xlord101/RaceIQ`

This repository contains:

- `src/raceiq/` — the actual RaceIQ Python backend / intelligence engine
- `config/` — FIA/model/event configuration
- `data/` — cached/public race data
- `tests/` — backend verification
- `lovable_extracted/` — CURRENT Lovable frontend that is being developed
- `loveable_reference/` — original/reference UI
- `frontend/` — older separate React frontend

The goal is NOT to redesign RaceIQ.

The goal is:

> CONNECT THE EXISTING LOVABLE FRONTEND TO THE ACTUAL RACEIQ BACKEND SO THAT THE LOVABLE UI BECOMES A REAL RACEIQ APPLICATION.

The backend is authoritative for calculations.

The Lovable frontend is authoritative for the current desired visual/product experience.

Do not replace either unnecessarily.

---

# 0. NON-NEGOTIABLE RULE

DO NOT ASSUME WHAT THE BACKEND DOES.

READ THE ACTUAL SOURCE CODE.

The following are authoritative:

1. Actual Python implementation in `src/raceiq/`
2. Actual configuration in `config/`
3. Actual tests in `tests/`
4. Actual current frontend in `lovable_extracted/`

Research papers, README files, architecture documents, and previous agent summaries are NOT substitutes for source code.

If documentation disagrees with implementation:

> implementation wins.

If the implementation does not establish something:

> do not invent it.

---

# 1. FIRST: CREATE AN INTEGRATION MAP — READ ONLY

Before editing anything, inspect the following.

## Backend

Read:

```text
src/raceiq/types.py
src/raceiq/config.py
src/raceiq/physics.py
src/raceiq/pipeline.py

src/raceiq/ingest/fastf1_loader.py
src/raceiq/ingest/openf1_client.py
src/raceiq/ingest/cache_manager.py

src/raceiq/track/segmentation.py

src/raceiq/inference/soc_observer.py
src/raceiq/inference/ers_mode.py
src/raceiq/inference/clipping.py
src/raceiq/inference/opponent_belief.py

src/raceiq/decision/pass_model.py
src/raceiq/decision/overtake_ev.py

src/raceiq/optimize/tier1_dp.py
src/raceiq/optimize/frontier.py
src/raceiq/optimize/tier2_mpc.py

src/raceiq/rules/ledger.py

src/raceiq/ui/contract.py
src/raceiq/ui/scenario.py
src/raceiq/ui/main.py

src/raceiq/baselines/
src/raceiq/validation/
```

Also inspect:

```text
config/rules_2026.json
config/circuits.json
config/hmm_priors.json
config/event_*.json
```

and the relevant tests.

---

# 2. READ THE LOVABLE FRONTEND

Inspect:

```text
lovable_extracted/src/lib/raceiq/adapter.ts
lovable_extracted/src/lib/raceiq/contracts.ts
lovable_extracted/src/lib/raceiq/store.tsx
lovable_extracted/src/lib/raceiq/engine.ts
lovable_extracted/src/lib/raceiq/sim.ts
lovable_extracted/src/lib/raceiq/dataSource.ts

lovable_extracted/src/components/raceiq/
lovable_extracted/src/routes/
```

Especially:

```text
HaasPanel.tsx
MatchupCard.tsx
TimingGrid.tsx
TrackMap.tsx
ReplayBar.tsx
ProvenanceTag.tsx
SiteHeader.tsx
```

---

# 3. PRODUCE A REAL DATA-FLOW TABLE BEFORE CODING

Create a temporary integration document/report containing:

| Lovable field | Backend source | Transformation | Provenance |
|---|---|---|---|
| position | actual timing/ingest | mapping only | ACTUAL |
| gap | actual timing/ingest | mapping only | ACTUAL |
| lap | session/timing | mapping | ACTUAL |
| SoC | soc_observer.py | adapter serialization | INFERRED |
| ERS mode | ers_mode.py | adapter serialization | INFERRED |
| clipping | clipping.py | adapter serialization | INFERRED |
| opponent belief | opponent_belief.py | adapter serialization | INFERRED |
| P(pass) | pass_model.py | adapter serialization | INFERRED |
| EV | overtake_ev.py | adapter serialization | INFERRED |
| posture | MPC/decision layer | adapter serialization | INFERRED |
| What-If result | counterfactual engine | adapter serialization | PROJECTED |

Do NOT fill a row with an invented backend source.

Find the real source.

---

# 4. CRITICAL: UNDERSTAND THE ACTUAL HMM

Read:

```text
src/raceiq/inference/opponent_belief.py
config/hmm_priors.json
tests/test_opponent_belief.py
```

The actual implementation currently defines an 8-state model:

```text
ERS:
H
M
Lharvest
Lderate

×

Overtake:
available
spent
```

Therefore:

```text
H | OT_avail
H | OT_spent
M | OT_avail
M | OT_spent
Lharvest | OT_avail
Lharvest | OT_spent
Lderate | OT_avail
Lderate | OT_spent
```

DO NOT replace this with the research paper's 40-state model.

DO NOT add tyre states from the paper.

DO NOT invent additional hidden states.

The repository implementation is authoritative.

Trace exactly:

```text
telemetry
→ emission features
→ emission likelihood
→ transition matrix
→ forward update
→ posterior belief
→ trap flag
→ decision layer
```

Document this mapping for the UI.

---

# 5. DO NOT REIMPLEMENT THE BACKEND IN TYPESCRIPT

This is one of the most important requirements.

The frontend must NOT independently recreate:

- SoC observer
- HMM
- pass model
- EV calculation
- DP
- MPC
- FIA rule calculations
- clipping detector
- track segmentation

The Python backend is the single source of truth.

The frontend should only:

```text
request/select state
        ↓
receive RaceIQ contract
        ↓
render it
```

The frontend may perform harmless display formatting such as:

```text
1.83 MJ
0.72 s
73%
ATTACK
```

but must not recalculate the underlying values.

---

# 6. IDENTIFY THE BEST BACKEND INTEGRATION METHOD

Before implementing, inspect whether the existing repository already exposes a suitable callable API/data-builder.

Prioritize:

### Option A — direct Python adapter/API

If the frontend can communicate with a Python service, expose a minimal API around the existing RaceIQ pipeline.

### Option B — precomputed factual replay artifacts

If the existing architecture is offline-first and a live Python service would unnecessarily complicate the project:

```text
historical telemetry
        ↓
RaceIQ Python pipeline
        ↓
serialized factual replay frames
        ↓
Lovable frontend
```

This is acceptable for historical replay.

### Option C — generated JSON contract

Create deterministic artifacts such as:

```text
data/replay/melbourne.json
data/replay/shanghai.json
data/replay/monza.json
```

where every frame contains:

```text
ACTUAL source state
+
INFERRED RaceIQ state
+
decision state
```

The frontend consumes these artifacts.

### DO NOT

Use:

```text
simulationAdapter
sim.ts
engine.ts
Math.random()
randomized pseudo telemetry
fake historical positions
fake tyre data
fake gaps
fake SoC
```

as the source for the final LIVE page.

---

# 7. PRESERVE THE LOVABLE ADAPTER ARCHITECTURE

The existing frontend already has:

```text
RaceIQAdapter
```

and:

```text
simulationAdapter
```

Use that seam.

Do NOT rip out the adapter abstraction.

Replace:

```text
simulationAdapter
```

with something conceptually like:

```text
raceIQAdapter
```

whose implementation obtains data from the real backend.

The UI should continue using:

```text
adapter.snapshotAt(...)
adapter.recommend(...)
adapter.whatIf(...)
```

where appropriate.

Components should not import:

```text
sim.ts
engine.ts
```

directly.

---

# 8. BUILD THE REAL SNAPSHOT CONTRACT

The frontend contract must represent one immutable RaceIQ frame.

At minimum:

```text
session
circuit
lap
timestamp
driver states
positions
gaps
SoC
SoC trend
ERS mode
Aero mode
overtake state
recommendation
belief
posture
compliance
provenance
```

Every field must have an explicit source.

Use:

```text
ACTUAL
INFERRED
PROJECTED / COUNTERFACTUAL
```

appropriately.

Important:

Position/gap sourced from historical timing:

```text
ACTUAL
```

SoC:

```text
INFERRED
```

ERS:

```text
INFERRED
```

HMM belief:

```text
INFERRED
```

RaceIQ recommendation:

```text
INFERRED
```

What-If:

```text
PROJECTED / COUNTERFACTUAL
```

---

# 9. FACTUAL REPLAY FIRST

Do NOT attempt What-If first.

First make this work:

```text
select circuit
        ↓
select historical session
        ↓
replay time
        ↓
backend generates/loads exact historical frame
        ↓
frontend renders frame
```

Use only supported historical events.

Initially target:

```text
Melbourne
Shanghai
Monza
```

Do not silently add Bahrain/Baku/Spa unless the actual current backend/config/data supports them correctly.

---

# 10. HISTORICAL REPLAY INTEGRITY

A historical frame must preserve the actual source data.

Do not force:

```text
22 drivers
```

if the source session does not contain 22 cars.

Missing cars remain missing.

Do not fabricate:

- positions
- gaps
- tyre compounds
- stints
- lap numbers
- sector states
- driver locations
- timestamps

If a field isn't available:

```text
null / unavailable
```

not:

```text
random value
```

---

# 11. MAP

The map must correspond to the selected circuit.

Do NOT use Melbourne geometry for every event.

Circuit:

```text
Melbourne → Melbourne geometry
Shanghai → Shanghai geometry
Monza → Monza geometry
```

Map driver locations must come from the factual replay source or a deterministic mapping from the actual telemetry.

Do not invent car positions.

---

# 12. LIVE PAGE

Preserve the Lovable design.

Do NOT turn LIVE into a technical dashboard.

Desired hierarchy:

```text
┌───────────────────────────────────────────────┐
│ RaceIQ | circuit | session | lap | replay    │
├───────────────────────┬───────────────────────┤
│                       │ Haas Driver / Matchup  │
│       TRACK MAP       │ SoC                    │
│                       │ ERS                    │
│                       │ GAP                    │
│                       │ RACEIQ CALL            │
├───────────────────────┴───────────────────────┤
│ 22-car compact timing/grid                    │
├───────────────────────────────────────────────┤
│ replay controls                               │
└───────────────────────────────────────────────┘
```

Keep:

- Haas OCO/BEA emphasis
- driver selection
- driver-v-driver comparison
- compact full-field grid
- map
- replay controls
- ACTUAL / INFERRED indicators

Do not add huge telemetry dashboards to LIVE.

---

# 13. HAAS DRIVER CARDS

Only Haas drivers receive prominent visual treatment.

Use actual existing assets for:

```text
Esteban Ocon
Oliver Bearman
```

Cards should show:

```text
photo
name
position
gap
estimated SoC
ERS state
RaceIQ call
```

Do not invent additional statistics merely to fill the card.

---

# 14. 22-DRIVER GRID

The grid must be genuinely interactive.

Clicking a driver should change:

```text
selected driver
comparison
map emphasis
timing emphasis
Haas matchup where applicable
```

Do not create separate fake state systems in each component.

The global replay snapshot should remain the single source of truth.

---

# 15. REPLAY CONTROLS

The replay clock must drive the entire UI.

One time state:

```text
replayTime
```

must determine:

```text
map
timing tower
selected driver
comparison
Haas cards
SoC
ERS
decision
```

Play/pause/step/speed must not cause different components to use different timestamps.

---

# 16. RACEIQ DECISION

The recommendation must come from the actual backend.

Possible UI posture values include:

```text
ATTACK
HOLD
DEFEND
HARVEST
```

But do not invent a recommendation simply because a UI card expects one.

Trace:

```text
HMM belief
+
SoC
+
track context
+
P(pass)
+
overtake eligibility
+
EV
+
rules/compliance
+
MPC/strategy
```

to the actual backend implementation.

Render the resulting recommendation.

---

# 17. WHY PAGE

Only after LIVE works.

WHY should expose the actual reasoning chain:

```text
Historical state
        ↓
Estimated energy
        ↓
Opponent belief
        ↓
Track context
        ↓
Overtake eligibility
        ↓
P(pass)
        ↓
EV
        ↓
RaceIQ action
```

Use progressive disclosure.

Do not expose raw backend internals everywhere.

---

# 18. WHAT IF PAGE

What-If MUST branch from an immutable historical snapshot.

Example:

```text
Historical frame:
OCO P6
NOR P5
gap = actual historical gap
SoC = inferred historical SoC
```

Then:

```text
WHAT IF OCO ATTACKS HERE?
```

The original frame must remain unchanged.

The output is:

```text
PROJECTED / COUNTERFACTUAL
```

not historical truth.

Do not let the What-If simulation overwrite the replay state.

---

# 19. CRITICAL WHAT-IF RULE

Do not create a second fake frontend simulation.

Use the actual RaceIQ decision/simulation infrastructure wherever it supports counterfactual reasoning.

If the existing backend cannot currently produce the requested counterfactual:

STOP.

Document the missing backend capability.

Do not fake the answer.

---

# 20. PROVENANCE

Every important displayed value needs provenance.

At minimum:

```text
ACTUAL
INFERRED
PROJECTED
```

Example:

```text
P6              ACTUAL
+0.72 s         ACTUAL
2.31 MJ         INFERRED
DEPLOY          INFERRED
P(pass) 0.64    INFERRED
EV +0.42        INFERRED
Projected P4    PROJECTED
```

Do not label inferred SoC as ACTUAL.

---

# 21. REMOVE SIMULATION FROM PRODUCTION UI

Once real integration works:

Search the entire `lovable_extracted` application for:

```text
sim.ts
simulationAdapter
engine.ts
Math.random
random
fake
mock
demo
placeholder
```

Determine which are:

1. legitimate development/test utilities
2. production data paths

Remove the simulation path from the default production experience.

It may remain behind an explicitly labelled developer/test mode if useful.

Never silently present it as factual replay.

---

# 22. BACKEND MUST REMAIN UNCHANGED WHERE POSSIBLE

Do not rewrite working RaceIQ algorithms simply to make frontend integration easier.

Especially do not rewrite:

```text
soc_observer.py
opponent_belief.py
pass_model.py
overtake_ev.py
tier1_dp.py
tier2_mpc.py
ledger.py
```

unless an actual integration incompatibility is proven.

If a backend change is required:

1. explain why
2. make the smallest change
3. add/update a test
4. run the backend suite
5. verify no algorithmic regression

---

# 23. BUILD A THIN SERIALIZATION/API LAYER

If necessary, add a small backend integration module whose sole purpose is:

```text
RaceIQ internal objects
        ↓
frontend contract
```

This layer should NOT contain new strategy logic.

Conceptually:

```python
def snapshot_to_frontend_contract(...):
    ...
```

It should serialize existing RaceIQ results.

This is preferable to duplicating logic in TypeScript.

---

# 24. DATA PIPELINE

The target architecture should become:

```text
                   HISTORICAL DATA
                         │
                         ▼
                FastF1 / OpenF1
                         │
                         ▼
                  RaceIQ ingest
                         │
                         ▼
                  Track context
                         │
              ┌──────────┴──────────┐
              ▼                     ▼
         SoC observer          ERS / clipping
              │                     │
              └──────────┬──────────┘
                         ▼
                 Opponent HMM
                         │
                         ▼
                  P(pass) model
                         │
                         ▼
                 Overtake EV
                         │
                         ▼
                    DP / MPC
                         │
                         ▼
              RaceIQ frame/contract
                         │
                         ▼
              frontend adapter
                         │
                         ▼
                LOVABLE FRONTEND
```

The frontend does not become the intelligence layer.

---

# 25. TESTING GATES

Do NOT proceed to the next phase unless the current phase passes.

## Gate 1 — backend baseline

Run:

```bash
pytest -q
```

Record:

```text
passed
failed
skipped
```

Do not assume the README's old numbers are current.

---

## Gate 2 — frontend baseline

Inside:

```text
lovable_extracted/
```

run the actual package-manager commands from its package.json.

At minimum:

```bash
npm run build
```

Fix baseline issues before integration.

---

# 26. INTEGRATION TESTS

Add tests for:

### Contract

Backend snapshot → frontend contract.

### Provenance

Every major field has correct provenance.

### Driver set

Source driver set = rendered driver set.

### Replay

Same timestamp produces deterministic identical frame.

### Circuit

Melbourne/Shanghai/Monza each use correct geometry/data.

### No simulation

Production adapter must not call `sim.ts`.

### HMM

Frontend displayed opponent belief must match backend output.

### SoC

Frontend displayed SoC must match backend serialized output.

### Recommendation

Frontend recommendation must match backend decision.

### What-If

Historical frame remains unchanged after counterfactual branch.

---

# 27. BROWSER VALIDATION

After integration, run the actual frontend.

Verify manually:

### LIVE

- page loads
- correct circuit
- correct historical session
- replay moves
- timing tower updates
- map updates
- Haas cards update
- selecting a driver works
- matchup changes
- provenance labels correct

### WHAT IF

- freeze frame
- create branch
- historical values remain unchanged
- projected values clearly labelled

### WHY

- reasoning chain matches backend

### IMPACT

- static explanation only
- no fabricated runtime claims

---

# 28. DO NOT CHANGE THE VISUAL DESIGN DURING BACKEND INTEGRATION

This is a major requirement.

First achieve:

> SAME UI + REAL DATA.

Only afterwards perform visual polish.

Do not simultaneously:

- redesign components
- change colors
- change layout
- add charts
- change navigation
- replace cards
- rewrite Tailwind
- introduce a new design system

unless required to fix a functional issue.

---

# 29. REMOVE DUPLICATE FRONTEND ARCHITECTURES ONLY AFTER SUCCESSFUL INTEGRATION

There are currently multiple frontend-related areas:

```text
frontend/
lovable_extracted/
loveable_reference/
```

Do NOT delete anything initially.

First establish:

```text
lovable_extracted = active product frontend
src/raceiq = backend intelligence
loveable_reference = visual reference
frontend = legacy/alternate
```

Only after the final application is working should obsolete code be considered for removal.

---

# 30. FINAL TARGET

The final repository should conceptually behave like:

```text
RaceIQ Python backend
        │
        │ real historical data
        │ real inference
        │ real decision logic
        ▼
RaceIQ frontend adapter
        │
        ▼
Lovable UI
```

NOT:

```text
Lovable UI
    ↓
fake simulation
    ↓
fake RaceIQ
```

---

# 31. REQUIRED IMPLEMENTATION ORDER

Implement exactly in this order:

### PHASE A
Repository inspection + integration map.

STOP and report.

### PHASE B
Backend → frontend contract mapping.

STOP and report.

### PHASE C
Real backend snapshot/replay adapter.

STOP and test.

### PHASE D
Real historical replay.

STOP and test.

### PHASE E
Connect inferred values:

```text
SoC
ERS
clipping
HMM
```

STOP and test.

### PHASE F
Connect decision outputs:

```text
P(pass)
Overtake eligibility
EV
posture
```

STOP and test.

### PHASE G
Connect LIVE page completely.

STOP and browser-test.

### PHASE H
Implement WHY using real backend outputs.

STOP and browser-test.

### PHASE I
Implement What-If using immutable historical state.

STOP and test.

### PHASE J
Remove simulation from production path.

STOP and grep/search entire frontend.

### PHASE K
Full integration regression.

Run:

```text
backend tests
frontend build
frontend browser smoke test
contract tests
provenance tests
replay determinism tests
```

### PHASE L
Final visual polish only after functionality is proven.

---

# 32. WHAT TO REPORT AFTER EVERY PHASE

For every phase report:

```text
PHASE:
FILES READ:
FILES CHANGED:
FILES NOT CHANGED:
WHAT WAS IMPLEMENTED:
WHAT WAS NOT IMPLEMENTED:
TESTS RUN:
TEST RESULTS:
BUILD RESULT:
BROWSER RESULT:
KNOWN LIMITATIONS:
NEXT PHASE:
```

Do not simply say:

> "Done."

---

# 33. ABSOLUTE PROHIBITIONS

DO NOT:

- invent telemetry
- invent historical positions
- invent SoC
- invent gaps
- invent tyre data
- invent HMM states
- use the paper's 40 states instead of the actual 8
- reimplement Python algorithms in TypeScript
- call simulation data historical
- silently fall back to random data
- use Melbourne geometry for another circuit
- force 22 drivers when source data has fewer
- overwrite historical state during What-If
- introduce obsolete pre-2026 DRS terminology into the 2026 operational UI
- redesign the Lovable frontend
- delete backend modules because the frontend doesn't currently use them
- modify working algorithms without evidence
- make a huge all-at-once rewrite

---

# 34. DEFINITION OF DONE

The project is complete only when:

```text
[ ] Actual backend is connected
[ ] Lovable UI remains visually faithful
[ ] Historical replay is factual
[ ] Replay is deterministic
[ ] Correct circuit geometry is used
[ ] Actual driver set is preserved
[ ] SoC comes from RaceIQ observer
[ ] ERS comes from RaceIQ inference
[ ] HMM comes from actual opponent_belief.py
[ ] P(pass) comes from backend
[ ] EV comes from backend
[ ] Recommendation comes from backend
[ ] ACTUAL / INFERRED / PROJECTED are correct
[ ] What-If branches immutably
[ ] WHY reflects real backend reasoning
[ ] Simulation is not the production data path
[ ] Backend tests pass
[ ] Frontend builds
[ ] Browser smoke test passes
[ ] No fabricated historical data
[ ] No unnecessary backend rewrite
```

The ultimate test is:

> If someone asks "Where did this number come from?", we can trace the displayed value from the Lovable component → frontend contract → backend adapter → exact RaceIQ Python module → source data/configuration.

That traceability is mandatory.