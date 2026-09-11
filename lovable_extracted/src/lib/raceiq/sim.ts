import { CIRCUITS, type CircuitId } from "./circuits";
import { DRIVERS } from "./drivers";
import type {
  ErsMode,
  Provenance,
  RaceIQDriverState,
  RaceIQSnapshot,
} from "./contracts";

/**
 * Placeholder data producer used until a RaceIQ backend adapter is connected.
 * Everything it emits is labelled SAMPLE — it is never presented as history.
 * The UI does not import this module directly; it goes through an adapter.
 */

export type { ErsMode, Provenance };
export type DriverState = RaceIQDriverState;
export type RaceSnapshot = RaceIQSnapshot;

/** Deterministic pseudo-noise so server and client render identically. */
function wave(seed: number, x: number) {
  return (
    Math.sin(x * 1.7 + seed * 2.3) * 0.55 +
    Math.sin(x * 0.61 + seed * 5.1) * 0.3 +
    Math.sin(x * 3.3 + seed * 1.1) * 0.15
  );
}

function hash(code: string) {
  let h = 0;
  for (let i = 0; i < code.length; i++) h = (h * 31 + code.charCodeAt(i)) % 997;
  return h / 997;
}

export function raceDuration(circuitId: CircuitId) {
  const c = CIRCUITS[circuitId];
  return c.laps * c.baseLapTime;
}

export function snapshotAt(circuitId: CircuitId, time: number): RaceSnapshot {
  const circuit = CIRCUITS[circuitId];
  const raw = DRIVERS.map((d, i) => {
    const seed = hash(d.code) * 10;
    const paceOffset = i * 0.42 + wave(seed, time / 240) * 0.9;
    const lapTime = circuit.baseLapTime + paceOffset + 1.2;
    const lapsDone = time / lapTime;
    const socBase = 0.55 + wave(seed + 3, time / 55) * 0.3;
    const soc = Math.min(0.97, Math.max(0.05, socBase));
    const socNext = Math.min(
      0.97,
      Math.max(0.05, 0.55 + wave(seed + 3, (time + 2) / 55) * 0.3),
    );
    return { d, lapsDone, lapTime, soc, socTrend: socNext - soc };
  });

  const ordered = [...raw].sort((a, b) => b.lapsDone - a.lapsDone);
  const leader = ordered[0]!;

  const drivers: DriverState[] = ordered.map((r, idx) => {
    const ahead = idx === 0 ? null : ordered[idx - 1]!;
    const lapFraction = r.lapsDone % 1;
    const detect = circuit.detectionLine;
    const inDetectionWindow = Math.abs(lapFraction - detect) < 0.05;
    let ersMode: ErsMode = "BALANCED";
    if (r.soc > 0.9 && r.socTrend > 0) ersMode = "CLIPPING";
    else if (r.socTrend > 0.012) ersMode = "RECHARGE";
    else if (r.socTrend > 0.004) ersMode = "HARVEST";
    else if (r.socTrend < -0.012) ersMode = "DEPLOY";
    return {
      code: r.d.code,
      position: idx + 1,
      lapFraction,
      lapsDone: r.lapsDone,
      gapToLeader: (leader.lapsDone - r.lapsDone) * r.lapTime,
      gapAhead: ahead ? (ahead.lapsDone - r.lapsDone) * r.lapTime : 0,
      soc: r.soc,
      socTrend: r.socTrend,
      ersMode,
      aeroMode: lapFraction > detect && lapFraction < circuit.activationLine + 0.08
        ? "STRAIGHT"
        : "CORNER",
      inDetectionWindow,
    };
  });

  const lap = Math.min(circuit.laps, Math.floor(leader.lapsDone) + 1);

  return {
    session: {
      source: "simulation",
      circuitId,
      lap,
      totalLaps: circuit.laps,
      time,
    },
    circuitId,
    time,
    lap,
    totalLaps: circuit.laps,
    positionsProvenance: "SAMPLE",
    energyProvenance: "INFERRED",
    drivers,
    byCode: Object.fromEntries(drivers.map((d) => [d.code, d])),
  };
}
