import json
import os
import sys
import pandas as pd

# Ensure we can import raceiq
sys.path.insert(0, os.path.abspath("src"))

from raceiq.pipeline import build_replay
from raceiq.decision import OvertakeContext, OvertakeEV, PassModel
from raceiq.validation.metrics import physics_frontier

def export_circuit(circuit: str, out_dir: str):
    print(f"Building replay for {circuit}...")
    try:
        replay = build_replay(circuit)
    except Exception as e:
        print(f"Error building replay for {circuit}: {e}")
        return
        
    total_laps = replay.total_laps
    if total_laps == 0:
        print(f"Skipping {circuit} (no laps)")
        return
        
    harvest_potential = float(getattr(replay.event_cfg, "brake_harvest_potential_mj", 3.0) or 3.0)
    frontier = physics_frontier(harvest_potential)
    ev_engine = OvertakeEV(config=replay.rules, pass_model=PassModel(), event=None)
    
    out = {
        "circuitId": circuit,
        "totalLaps": total_laps,
        "laps": []
    }
    
    haas_codes = ["MAG", "HUL", "BEA", "OCO"]
    
    for lap in range(1, total_laps + 1):
        tower = replay.timing_tower(lap)
        if tower.empty:
            continue
            
        drivers_state = []
        
        for rank, row in tower.iterrows():
            code = row["driver"]
            pos = int(row["position"])
            gapToLeader = float(row["interval_s"]) if pd.notna(row["interval_s"]) else None
            
            gapAhead = None
            if rank > 0:
                prev_row = tower.iloc[rank - 1]
                if gapToLeader is not None and pd.notna(prev_row["interval_s"]):
                    gapAhead = gapToLeader - float(prev_row["interval_s"])
            elif gapToLeader is not None:
                gapAhead = 0.0
                
            est_soc_mj = float(row["est_soc_mj"])
            mode = str(row["mode"]).upper()
            if mode == "BALANCE": mode = "BALANCED"
            
            drv_state = {
                "code": code,
                "position": pos,
                "gapToLeader": gapToLeader,
                "gapAhead": gapAhead,
                "soc": est_soc_mj / replay.rules.soc_window_mj if pd.notna(est_soc_mj) else None,
                "ersMode": mode,
            }
            
            if code in haas_codes and gapAhead is not None and rank > 0:
                rival_row = tower.iloc[rank - 1]
                rival_soc = float(rival_row["est_soc_mj"])
                speed_trace = replay.speed_trace(code, lap)
                speed = 250.0
                if not speed_trace.empty:
                    speed = float(speed_trace["Speed"].max())
                
                ctx = OvertakeContext(
                    gap_ahead_s=gapAhead,
                    closing_speed_kph=max(speed - 250.0, 0.0),
                    straight_remaining_m=650.0,
                    tyre_age_delta_laps=float(lap % 20) * 0.2, 
                    own_est_soc=est_soc_mj,
                    rival_est_soc=rival_soc,
                    belief=None,
                    overtake_mode_active=False,
                    circuit_harvest_potential_mj=harvest_potential,
                    laps_remaining=max(total_laps - lap, 1),
                    position_before=pos,
                    legal=True,
                )
                dec = ev_engine.evaluate(ctx, frontier)
                drv_state["recommendation"] = {
                    "posture": dec.recommendation.upper(),
                    "confidence": 0.85,
                    "passProbability": float(dec.p_pass),
                    "overtakeEv": float(dec.ev),
                    "reason": dec.why
                }
            
            drivers_state.append(drv_state)
            
        out["laps"].append({
            "lap": lap,
            "drivers": drivers_state
        })
        
    os.makedirs(out_dir, exist_ok=True)
    out_file = os.path.join(out_dir, f"{circuit}_factual.json")
    with open(out_file, "w") as f:
        json.dump(out, f, indent=2)
    print(f"Wrote {out_file}")

if __name__ == "__main__":
    out_dir = os.path.abspath("frontend/src/data")
    for c in ["Melbourne", "Shanghai", "Monza"]:
        export_circuit(c, out_dir)
