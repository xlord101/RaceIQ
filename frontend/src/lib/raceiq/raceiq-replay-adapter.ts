import type {
  RaceIQAdapter,
  RaceIQCircuit,
  RaceIQDriverState,
  RaceIQSnapshot,
  RaceIQRecommendation,
  RaceIQWhatIfBranch,
  Posture,
  RiskLevel
} from "./contracts";
import { CIRCUITS, type CircuitId, CIRCUIT_LIST } from "./circuits";
import { DRIVER_BY_CODE } from "./drivers";

import melbourneData from "../../data/Melbourne_factual.json";
import shanghaiData from "../../data/Shanghai_factual.json";
import monzaData from "../../data/Monza_factual.json";

const trackData: Record<string, any> = {
  Melbourne: melbourneData,
  Shanghai: shanghaiData,
  Monza: monzaData,
};

export const raceiqReplayAdapter: RaceIQAdapter = {
  id: "raceiq-replay",
  kind: "recorded",
  circuits: CIRCUIT_LIST,
  circuit: (circuitId) => CIRCUITS[circuitId as CircuitId],
  driver: (code) => DRIVER_BY_CODE[code],
  duration: (circuitId) => {
    const track = trackData[circuitId];
    if (!track) return 3600;
    const base = CIRCUITS[circuitId as CircuitId]?.baseLapTime || 90;
    return track.totalLaps * base;
  },
  snapshotAt: (circuitId, time) => {
    const track = trackData[circuitId];
    if (!track) {
      throw new Error(`Data for ${circuitId} not found`);
    }

    const baseLapTime = CIRCUITS[circuitId as CircuitId]?.baseLapTime || 90;
    
    // UI time maps to integer laps
    let currentLap = Math.floor(time / baseLapTime) + 1;
    currentLap = Math.max(1, Math.min(currentLap, track.totalLaps));

    const baseLapFraction = (time % baseLapTime) / baseLapTime;

    // Use lap data if available, fallback to lap 1
    const lapData = track.laps.find((l: any) => l.lap === currentLap) || track.laps[0];

    const byCode: Record<string, RaceIQDriverState> = {};
    const drivers: RaceIQDriverState[] = [];

    for (const d of lapData.drivers) {
      const dt = d.gapToLeader ?? 0;
      
      // Calculate fraction of track based on time behind leader
      let lf = (baseLapFraction - (dt / baseLapTime) + 1.0) % 1.0;
      
      const state: RaceIQDriverState = {
        code: d.code,
        position: d.position,
        gapToLeader: d.gapToLeader ?? undefined,
        gapAhead: d.gapAhead ?? undefined,
        soc: d.soc ?? undefined,
        ersMode: d.ersMode ?? undefined,
        lapFraction: lf,
        lapsDone: currentLap - 1,
      };
      drivers.push(state);
      byCode[d.code] = state;
    }

    return {
      session: {
        source: "raceiq-replay",
        circuitId,
        lap: currentLap,
        totalLaps: track.totalLaps,
        time: time,
      },
      circuitId,
      time,
      lap: currentLap,
      totalLaps: track.totalLaps,
      positionsProvenance: "ACTUAL",
      energyProvenance: "INFERRED",
      drivers,
      byCode,
    };
  },
  recommend: (snapshot, code) => {
    const track = trackData[snapshot.circuitId];
    if (!track) return undefined;
    
    const lapData = track.laps.find((l: any) => l.lap === snapshot.lap);
    if (!lapData) return undefined;
    
    const driver = lapData.drivers.find((d: any) => d.code === code);
    if (!driver || !driver.recommendation) return undefined;

    return driver.recommendation as RaceIQRecommendation;
  },
  whatIf: (snapshot, code, action) => {
    const state = snapshot.byCode[code];
    if (!state) return undefined;

    let projPos = state.position;
    let projGap = state.gapAhead;
    let cost = 0.0;
    let outcome = "Position maintained";
    let risk: RiskLevel = "LOW";
    let oppResp = "Maintained pace";

    if (action === "ATTACK") {
      if (state.position > 1) {
        projPos = state.position - 1;
        outcome = "Successful overtake";
        projGap = 1.2;
      }
      cost = 0.4;
      risk = "HIGH";
      oppResp = "Defended aggressively";
    } else if (action === "HOLD") {
      cost = 0.1;
    } else if (action === "HARVEST") {
      cost = -0.2;
      projGap = (state.gapAhead || 0) + 0.5;
    } else if (action === "DEFEND") {
      cost = 0.2;
      risk = "MEDIUM";
      outcome = "Successfully defended";
      oppResp = "Attempted pass but failed";
    }

    return {
      seed: { ...snapshot.session, driver: code, position: state.position, gapAhead: state.gapAhead, soc: state.soc },
      action,
      projectedPosition: projPos,
      projectedGap: projGap,
      energyCost: cost,
      outcome,
      risk,
      opponentResponse: oppResp,
    };
  },
};
