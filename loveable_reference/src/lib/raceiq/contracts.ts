/**
 * RaceIQ frontend data contracts.
 *
 * These types are the ONLY thing the UI consumes. A thin adapter maps the real
 * RaceIQ backend outputs (actual / inferred / counterfactual) onto them.
 *
 * Rules baked into these types:
 * - Anything the backend may not provide is optional. The UI renders a neutral
 *   placeholder instead of a fabricated number.
 * - Provenance travels with the data, never hardcoded in a component.
 * - No calculation lives here. This file is shape only.
 */

export type Provenance = "SAMPLE" | "ACTUAL" | "INFERRED" | "PROJECTED";

export type ErsMode = "DEPLOY" | "HARVEST" | "RECHARGE" | "BALANCED" | "CLIPPING";

export type AeroMode = "STRAIGHT" | "CORNER";

export type Posture = "ATTACK" | "HOLD" | "DEFEND" | "HARVEST";

export type RiskLevel = "LOW" | "MEDIUM" | "HIGH";

/** Static line-up metadata. Supplied by the adapter, not derived in the UI. */
export interface DriverIdentity {
  code: string;
  name?: string | undefined;
  team?: string | undefined;
  /** Marker / bar colour. */
  color?: string | undefined;
  /** Team the product tracks (Haas today). */
  tracked?: boolean | undefined;
  /** Absolute or bundled portrait URL, if one exists. */
  image?: string | undefined;
}

/** One car at one instant of a session. Only code + position are guaranteed. */
export interface RaceIQDriverState {
  code: string;
  position: number;
  /** 0..1 position around the lap, used for the map. */
  lapFraction?: number | undefined;
  lapsDone?: number | undefined;
  /** Seconds. */
  gapToLeader?: number | undefined;
  gapAhead?: number | undefined;
  /** 0..1 estimated state of charge. */
  soc?: number | undefined;
  /** Change in SoC over the sampling window, in 0..1 units. */
  socTrend?: number | undefined;
  ersMode?: ErsMode | undefined;
  aeroMode?: AeroMode | undefined;
  inDetectionWindow?: boolean | undefined;
}

/** Immutable identifiers of the source state. What-If branches are seeded from this. */
export interface SessionRef {
  /** Adapter identifier, e.g. "simulation" or "raceiq-replay". */
  source: string;
  sessionId?: string | undefined;
  raceId?: string | undefined;
  circuitId: string;
  lap: number;
  totalLaps: number;
  /** Race clock in seconds. */
  time: number;
}

export interface RaceIQSnapshot {
  session: SessionRef;
  circuitId: string;
  time: number;
  lap: number;
  totalLaps: number;
  /** How positions/gaps in this snapshot were obtained. */
  positionsProvenance: Provenance;
  /** How energy/ERS values in this snapshot were obtained. */
  energyProvenance: Provenance;
  drivers: RaceIQDriverState[];
  byCode: Record<string, RaceIQDriverState>;
}

export interface ProvenancedFactor {
  label: string;
  value: string;
  provenance: Provenance;
}

export interface RaceIQRecommendation {
  posture: Posture;
  headline?: string | undefined;
  reason?: string | undefined;
  /** 0..1 */
  confidence?: number | undefined;
  /** 0..1 */
  passProbability?: number | undefined;
  /** Seconds of net race time. */
  overtakeEv?: number | undefined;
  /** 0..1 SoC cost. */
  energyCost?: number | undefined;
  constraints?: string[] | undefined;
  factors?: ProvenancedFactor[] | undefined;
}

export interface RaceIQWhatIfBranch {
  /** Frozen source state. Never mutated by a branch. */
  seed: SessionRef & {
    driver: string;
    position?: number | undefined;
    gapAhead?: number | undefined;
    soc?: number | undefined;
  };
  action: Posture;
  projectedPosition?: number | undefined;
  projectedGap?: number | undefined;
  projectedSoc?: number | undefined;
  energyCost?: number | undefined;
  outcome?: string | undefined;
  risk?: RiskLevel | undefined;
  confidence?: number | undefined;
  opponentResponse?: string | undefined;
}

/** Track geometry and presentation metadata for one supported circuit. */
export interface BrakingZone {
  /** Approximate normalized lap position; presentation guide, not telemetry. */
  at: number;
  width: number;
  label: string;
}

export interface RaceIQCircuit {
  id: string;
  name: string;
  event: string;
  country?: string | undefined;
  laps: number;
  baseLapTime?: number | undefined;
  /** Circuit centerline path used by the map. */
  path: string;
  viewBox: string;
  sectors?: [number, number] | undefined;
  /** Fraction of the lap where the Overtake Detection Line sits. */
  detectionLine?: number | undefined;
  /** Fraction of the lap where the Overtake Activation Line sits. */
  activationLine?: number | undefined;
  brakingZones?: BrakingZone[] | undefined;
}

/**
 * The single seam between the UI and any RaceIQ backend.
 * Implement this and the whole product switches data source.
 */
export interface RaceIQAdapter {
  id: string;
  kind: "simulation" | "recorded" | "live";
  /** Circuits the product is allowed to expose. */
  circuits: RaceIQCircuit[];
  circuit: (circuitId: string) => RaceIQCircuit | undefined;
  driver: (code: string) => DriverIdentity | undefined;
  duration: (circuitId: string) => number;
  snapshotAt: (circuitId: string, time: number) => RaceIQSnapshot;
  /** Optional: a backend may not expose a posture for every driver. */
  recommend?: (snapshot: RaceIQSnapshot, code: string) => RaceIQRecommendation | undefined;
  /** Optional: counterfactual branching may be unavailable. */
  whatIf?: (
    snapshot: RaceIQSnapshot,
    code: string,
    action: Posture,
  ) => RaceIQWhatIfBranch | undefined;
}

export function driverStateOf(
  snapshot: RaceIQSnapshot,
  code: string,
): RaceIQDriverState | undefined {
  return snapshot.byCode[code];
}
