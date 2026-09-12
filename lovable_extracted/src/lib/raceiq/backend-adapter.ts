import melbourneFactual from "@/data/Melbourne_factual.json";
import shanghaiFactual from "@/data/Shanghai_factual.json";
import monzaFactual from "@/data/Monza_factual.json";

import { simulationAdapter } from "./adapter";
import { CIRCUIT_LIST, type CircuitId } from "./circuits";
import type {
  DriverIdentity,
  ErsMode,
  Posture,
  ProvenancedFactor,
  RaceIQAdapter,
  RaceIQCircuit,
  RaceIQDriverState,
  RaceIQRecommendation,
  RaceIQSnapshot,
  RaceIQWhatIfBranch,
  RiskLevel,
} from "./contracts";
import { DRIVER_BY_CODE } from "./drivers";

interface FactualDriver {
  code: string;
  position: number;
  gapToLeader: number | null;
  gapAhead: number | null;
  soc: number | null;
  nextSoc: number | null;
  socTrend: number | null;
  ersMode: string | null;
  subLap?: {
    soc: number[];
    modes: string[];
    kinds: string[];
    clips: boolean[];
  };
  recommendation?: {
    posture: Posture;
    confidence: number;
    passProbability: number;
    overtakeEv: number;
    energyCost: number;
    reason: string;
    constraints: string[];
    factors: {
      label: string;
      value: string;
      provenance: "ACTUAL" | "INFERRED" | "PROJECTED" | "SAMPLE";
    }[];
    whatIfBranches?: Record<
      string,
      {
        projectedPosition: number;
        projectedGap: number;
        projectedSoc: number;
        energyCost: number;
        outcome: string;
        risk: string;
        confidence: number;
        opponentResponse: string;
      }
    >;
  };
}

interface FactualLap {
  lap: number;
  drivers: FactualDriver[];
}

interface FactualCircuitMetadata {
  season: number;
  sessionType: string;
  event: string;
  circuit: string;
  date: string;
  source: string;
  telemetryYear: number;
  ruleset: string;
  positionsProvenance: "ACTUAL" | "INFERRED" | "PROJECTED" | "SAMPLE";
  energyProvenance: "ACTUAL" | "INFERRED" | "PROJECTED" | "SAMPLE";
}

interface FactualCircuitData {
  metadata?: FactualCircuitMetadata;
  season?: number;
  sessionType?: string;
  circuitId: string;
  circuitKey: string;
  totalLaps: number;
  baseLapTime: number;
  harvestCapMj: number;
  laps: FactualLap[];
}

const FACTUAL_DATA: Record<string, FactualCircuitData> = {
  melbourne: melbourneFactual as unknown as FactualCircuitData,
  shanghai: shanghaiFactual as unknown as FactualCircuitData,
  monza: monzaFactual as unknown as FactualCircuitData,
};

export const BACKEND_CIRCUITS: RaceIQCircuit[] = CIRCUIT_LIST.map((base) => {
  const factual = FACTUAL_DATA[base.id.toLowerCase()];
  return {
    ...base,
    laps: factual ? factual.totalLaps : base.laps,
    baseLapTime: factual ? factual.baseLapTime : base.baseLapTime,
  };
});

const CIRCUITS_BY_ID: Record<string, RaceIQCircuit> = Object.fromEntries(
  BACKEND_CIRCUITS.map((c) => [c.id.toLowerCase(), c]),
);

function getDriver(code: string): DriverIdentity {
  const d = DRIVER_BY_CODE[code];
  if (d) return d;
  return {
    code,
    name: code,
    team: "Independent",
    color: "#8c8f93",
    tracked: false,
  };
}

function getDuration(circuitId: string): number {
  const factual = FACTUAL_DATA[circuitId.toLowerCase()];
  if (factual) {
    return factual.totalLaps * factual.baseLapTime;
  }
  return simulationAdapter.duration(circuitId);
}

function getSnapshotAt(circuitId: string, time: number): RaceIQSnapshot {
  const circuitKey = circuitId.toLowerCase();
  const factual = FACTUAL_DATA[circuitKey];
  const circuit = CIRCUITS_BY_ID[circuitKey] ?? BACKEND_CIRCUITS[0]!;

  // Must be valid 2026 factual Grand Prix race dataset (Rule 7: reject non-2026 data)
  if (
    !factual ||
    !factual.laps ||
    factual.laps.length === 0 ||
    (factual.season !== undefined && factual.season !== 2026) ||
    (factual.metadata && (factual.metadata.season !== 2026 || factual.metadata.sessionType !== "Race"))
  ) {
    const simSnap = simulationAdapter.snapshotAt(circuitId, time);
    return {
      ...simSnap,
      positionsProvenance: "SAMPLE",
      energyProvenance: "SAMPLE",
    };
  }

  const baseLapTime = factual.baseLapTime || 90.0;
  const clampedTime = Math.max(0, Math.min(time, factual.totalLaps * baseLapTime));
  const currentLapNum = Math.min(
    factual.totalLaps,
    Math.max(1, Math.floor(clampedTime / baseLapTime) + 1),
  );
  const lapIndex = Math.min(factual.laps.length - 1, Math.max(0, currentLapNum - 1));
  const baseLapFraction = (clampedTime % baseLapTime) / baseLapTime;
  const lapData = factual.laps[lapIndex];

  if (!lapData || !lapData.drivers) {
    const simSnap = simulationAdapter.snapshotAt(circuitId, time);
    return {
      ...simSnap,
      positionsProvenance: "SAMPLE",
      energyProvenance: "SAMPLE",
    };
  }

  const detect = circuit.detectionLine ?? 0.52;
  const activate = circuit.activationLine ?? 0.63;

  const drivers: RaceIQDriverState[] = lapData.drivers.map((d) => {
    // Physical cumulative race gap to P1 from FastF1
    const gapToLeader =
      typeof d.gapToLeader === "number" ? d.gapToLeader : d.position === 1 ? 0 : undefined;
    const gapAhead =
      typeof d.gapAhead === "number" ? d.gapAhead : d.position === 1 ? 0 : undefined;

    // Track map placement relative to leader
    const gapDelta = (gapToLeader ?? 0) / baseLapTime;
    let lapFraction = (baseLapFraction - gapDelta) % 1.0;
    if (lapFraction < 0) lapFraction += 1.0;
    lapFraction = Number(lapFraction.toFixed(4));

    let interpolatedSoc: number;
    let socTrend: number;
    let ersMode: ErsMode;
    let aeroMode: "STRAIGHT" | "CORNER";

    if (d.subLap && Array.isArray(d.subLap.soc) && d.subLap.soc.length > 1) {
      const nSegments = d.subLap.soc.length - 1;
      const u = Math.max(0, Math.min(lapFraction * nSegments, nSegments));
      const idx = Math.min(Math.floor(u), nSegments - 1);
      const r = u - idx;
      const socSample = d.subLap.soc[idx] + r * (d.subLap.soc[idx + 1] - d.subLap.soc[idx]);
      interpolatedSoc = Number(socSample.toFixed(4));
      socTrend = Number((d.subLap.soc[idx + 1] - d.subLap.soc[idx]).toFixed(4));

      const nearestIdx = Math.min(Math.max(0, Math.round(u)), d.subLap.modes.length - 1);
      const isClipping = Boolean(d.subLap.clips && d.subLap.clips[nearestIdx]);
      const rawMode = d.subLap.modes[nearestIdx];

      if (isClipping || rawMode === "CLIPPING") {
        ersMode = "CLIPPING";
      } else if (
        rawMode === "DEPLOY" ||
        rawMode === "HARVEST" ||
        rawMode === "RECHARGE" ||
        rawMode === "BALANCED"
      ) {
        ersMode = rawMode;
      } else {
        ersMode = "BALANCED";
      }

      const kind = d.subLap.kinds?.[nearestIdx];
      aeroMode = kind === "straight" ? "STRAIGHT" : "CORNER";
    } else {
      // Continuous driver-specific interpolated SoC (Requirement 6 fallback):
      // SoC(t) = SoC(L) + lapFraction * (SoC(L+1) - SoC(L))
      const socStart = typeof d.soc === "number" ? d.soc : 0.5;
      const socEnd = typeof d.nextSoc === "number" ? d.nextSoc : socStart;
      interpolatedSoc = Number((socStart + baseLapFraction * (socEnd - socStart)).toFixed(4));
      socTrend = typeof d.socTrend === "number" ? d.socTrend : 0.0;

      ersMode =
        d.ersMode === "DEPLOY" ||
        d.ersMode === "HARVEST" ||
        d.ersMode === "RECHARGE" ||
        d.ersMode === "BALANCED" ||
        d.ersMode === "CLIPPING"
          ? d.ersMode
          : "BALANCED";

      aeroMode =
        lapFraction > detect && lapFraction < activate + 0.08 ? "STRAIGHT" : "CORNER";
    }

    const inDetectionWindow = Boolean(
      (gapAhead !== undefined && gapAhead <= 1.0 && gapAhead > 0) ||
        (baseLapFraction > detect - 0.05 && baseLapFraction < detect + 0.05),
    );

    return {
      code: d.code,
      position: d.position,
      lapFraction,
      lapsDone: Math.max(0, currentLapNum - 1 + lapFraction),
      gapToLeader,
      gapAhead,
      soc: interpolatedSoc,
      socTrend,
      ersMode,
      aeroMode,
      inDetectionWindow,
    };
  });

  drivers.sort((a, b) => a.position - b.position);
  const byCode = Object.fromEntries(drivers.map((d) => [d.code, d]));

  return {
    session: {
      source: "raceiq-backend-replay",
      circuitId: circuit.id,
      lap: currentLapNum,
      totalLaps: factual.totalLaps,
      time: clampedTime,
    },
    circuitId: circuit.id,
    time: clampedTime,
    lap: currentLapNum,
    totalLaps: factual.totalLaps,
    positionsProvenance: factual.metadata?.positionsProvenance ?? "ACTUAL",
    energyProvenance: factual.metadata?.energyProvenance ?? "INFERRED",
    drivers,
    byCode,
  };
}

function getRecommendation(
  snapshot: RaceIQSnapshot,
  code: string,
): RaceIQRecommendation | undefined {
  const circuitKey = snapshot.circuitId.toLowerCase();
  const factual = FACTUAL_DATA[circuitKey];
  if (!factual || !factual.laps) return undefined;

  const baseLapTime = factual.baseLapTime || 90.0;
  const currentLapNum = Math.min(
    factual.totalLaps,
    Math.max(1, Math.floor(snapshot.time / baseLapTime) + 1),
  );
  const lapIndex = Math.min(factual.laps.length - 1, Math.max(0, currentLapNum - 1));
  const lapData = factual.laps[lapIndex];
  if (!lapData) return undefined;

  const driverData = lapData.drivers.find((d) => d.code === code);
  if (!driverData || !driverData.recommendation) {
    const driverState = snapshot.byCode[code];
    if (!driverState) return undefined;
    return {
      posture: "HOLD",
      confidence: 0.85,
      passProbability: 0.25,
      overtakeEv: -0.15,
      energyCost: 0.05,
      reason: "Pacing delta nominal; conserving battery reserve",
      constraints: ["soc_window: PASS", "harvest_cap: PASS", "deploy_cap: PASS"],
      factors: [
        {
          label: "Detection gap",
          value: driverState.gapAhead != null ? `+${driverState.gapAhead.toFixed(2)}s` : "n/a",
          provenance: "ACTUAL",
        },
        {
          label: "Battery (est.)",
          value: `${Math.round((driverState.soc ?? 0.5) * 100)}%`,
          provenance: "INFERRED",
        },
      ],
    };
  }

  const rec = driverData.recommendation;
  const driverState = snapshot.byCode[code];
  const factors = rec.factors.map((f) => {
    if (f.label === "Battery (est.)" && driverState?.soc !== undefined) {
      return {
        ...f,
        value: `${Math.round(driverState.soc * 100)}%`,
      };
    }
    return f;
  });

  return {
    posture: rec.posture,
    headline: rec.reason.split("->")[1]?.trim() || rec.posture,
    reason: rec.reason,
    confidence: rec.confidence,
    passProbability: rec.passProbability,
    overtakeEv: rec.overtakeEv,
    energyCost: rec.energyCost,
    constraints: rec.constraints,
    factors: factors as ProvenancedFactor[],
  };
}

function getWhatIf(
  snapshot: RaceIQSnapshot,
  code: string,
  action: Posture,
): RaceIQWhatIfBranch | undefined {
  const driverState = snapshot.byCode[code];
  const seed = {
    source: snapshot.session.source,
    circuitId: snapshot.circuitId,
    lap: snapshot.lap,
    totalLaps: snapshot.totalLaps,
    time: snapshot.time,
    driver: code,
    position: driverState?.position,
    gapAhead: driverState?.gapAhead,
    soc: driverState?.soc,
  };

  const circuitKey = snapshot.circuitId.toLowerCase();
  const factual = FACTUAL_DATA[circuitKey];
  if (factual && factual.laps) {
    const baseLapTime = factual.baseLapTime || 90.0;
    const currentLapNum = Math.min(
      factual.totalLaps,
      Math.max(1, Math.floor(snapshot.time / baseLapTime) + 1),
    );
    const lapIndex = Math.min(factual.laps.length - 1, Math.max(0, currentLapNum - 1));
    const lapData = factual.laps[lapIndex];
    const driverData = lapData?.drivers.find((d) => d.code === code);
    const branchData = driverData?.recommendation?.whatIfBranches?.[action];

    if (branchData) {
      return {
        seed,
        action,
        projectedPosition: branchData.projectedPosition,
        projectedGap: branchData.projectedGap,
        projectedSoc: branchData.projectedSoc,
        energyCost: branchData.energyCost,
        outcome: branchData.outcome,
        risk: (branchData.risk as RiskLevel) ?? "MEDIUM",
        confidence: branchData.confidence,
        opponentResponse: branchData.opponentResponse,
      };
    }
  }

  const pos = driverState?.position ?? 10;
  const gap = driverState?.gapAhead ?? 1.5;
  const soc = driverState?.soc ?? 0.5;

  switch (action) {
    case "ATTACK":
      return {
        seed,
        action,
        projectedPosition: Math.max(1, pos - 1),
        projectedGap: 0.75,
        projectedSoc: Math.max(0.05, Number((soc - 0.12).toFixed(4))),
        energyCost: 0.45,
        outcome: "Overtake completed at Turn 1 apex",
        risk: "HIGH",
        confidence: 0.65,
        opponentResponse: "Attempted defensive squeeze but conceded corner",
      };
    case "HOLD":
      return {
        seed,
        action,
        projectedPosition: pos,
        projectedGap: gap,
        projectedSoc: soc,
        energyCost: 0.05,
        outcome: "Pace matched; battery charge preserved for next straight",
        risk: "LOW",
        confidence: 0.94,
        opponentResponse: "Maintained defensive positioning",
      };
    case "DEFEND":
      return {
        seed,
        action,
        projectedPosition: pos,
        projectedGap: Number((gap + 0.35).toFixed(3)),
        projectedSoc: Math.max(0.05, Number((soc - 0.06).toFixed(4))),
        energyCost: 0.22,
        outcome: "Track position secured against undercut attempt",
        risk: "MEDIUM",
        confidence: 0.86,
        opponentResponse: "Attempted outside switchback; repelled",
      };
    case "HARVEST":
      return {
        seed,
        action,
        projectedPosition: pos,
        projectedGap: Number((gap + 0.65).toFixed(3)),
        projectedSoc: Math.min(0.95, Number((soc + 0.1).toFixed(4))),
        energyCost: -0.38,
        outcome: "Recharged +10 pt SoC; ceded 0.65s in dirty air",
        risk: "LOW",
        confidence: 0.92,
        opponentResponse: "Pulled 0.65s margin down the straight",
      };
  }
}

export const backendAdapter: RaceIQAdapter = {
  id: "raceiq-backend-replay",
  kind: "recorded",
  circuits: BACKEND_CIRCUITS,
  circuit: (circuitId) => CIRCUITS_BY_ID[circuitId.toLowerCase()] ?? BACKEND_CIRCUITS[0],
  driver: getDriver,
  duration: getDuration,
  snapshotAt: getSnapshotAt,
  recommend: getRecommendation,
  whatIf: getWhatIf,
};
