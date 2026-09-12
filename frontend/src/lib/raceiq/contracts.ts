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

export interface HmmBeliefState {
  "H|OT_avail": number;
  "H|OT_spent": number;
  "M|OT_avail": number;
  "M|OT_spent": number;
  "Lharvest|OT_avail": number;
  "Lharvest|OT_spent": number;
  "Lderate|OT_avail": number;
  "Lderate|OT_spent": number;
  p_ot_avail: number;
  p_Lderate?: number | undefined;
  p_Lharvest?: number | undefined;
  trap_flag?: boolean | undefined;
  trap_prob?: number | undefined;
}

export interface PassModelFeatures {
  gap_ahead_s: number;
  closing_speed_kph: number;
  straight_remaining_m: number;
  tyre_age_delta_laps: number;
  own_est_soc: number;
  rival_est_soc: number;
  rival_P_Lderate: number;
  rival_P_Lharvest: number;
  trap_flag: boolean;
  overtake_mode_active: boolean;
  circuit_harvest_potential_mj: number;
  laps_remaining: number;
  p_pass?: number | undefined;
  model_status?: "HEURISTIC" | "TRAINED_ML" | undefined;
}

export interface OvertakeEvBreakdown {
  p_pass: number;
  points_gain: number;
  repass_cost_pts: number;
  repayment_cost_s: number;
  repayment_cost_pts: number;
  illegal_penalty: number;
  strategic_ev: number;
  recommendation: Posture;
  repass_risk: number;
  why?: string | undefined;
}

export interface TimelineSample {
  lap: number;
  time: number;
  soc: number;
  ersMode: ErsMode;
  isClipping: boolean;
  gapAhead: number | null;
  gapToLeader: number | null;
  pPass?: number | null | undefined;
  strategicEv?: number | null | undefined;
  posture?: Posture | null | undefined;
  pLderate?: number | null | undefined;
  pLharvest?: number | null | undefined;
  pOtAvail?: number | null | undefined;
  trapFlag?: boolean | null | undefined;
}

export interface RaceIQAnalysisSnapshot {
  // A. RACE STATE
  raceState: {
    circuitId: string;
    circuitName: string;
    lap: number;
    totalLaps: number;
    time: number;
    driver: string;
    rival: string | null;
    position: number;
    gapAhead: number | null;
    cumulativeGapToLeader: number | null;
    lapFraction: number;
  };

  // B. ACTUAL TELEMETRY / OBSERVATIONS
  telemetry: {
    available: boolean;
    provenance: Provenance;
    speed?: number | null | undefined;
    throttle?: number | null | undefined;
    brake?: number | null | undefined;
    distance?: number | null | undefined;
    relevantTrackSegment?: string | null | undefined;
    detectionWindow: {
      detectionLine: number;
      activationLine: number;
      inWindow: boolean;
    };
    straightContext?: {
      longestStraightM?: number | undefined;
      closingSpeedKph?: number | undefined;
      detectionGapS?: number | null | undefined;
    };
    subLapCheckpoints?: {
      soc: number[];
      modes: string[];
      kinds: string[];
      clips: boolean[];
      distance?: number[] | undefined;
      speed?: number[] | undefined;
      throttle?: number[] | undefined;
      brake?: number[] | undefined;
    } | undefined;
  };

  // C. ENERGY
  energy: {
    soc: number;
    socTrend: number;
    ersMode: ErsMode;
    isClipping: boolean;
    energyProvenance: Provenance;
    harvestCapMj: number;
    harvestPotentialMj?: number | null | undefined;
  };

  // D. OPPONENT INFERENCE
  opponentInference: {
    rivalCode: string | null;
    rivalSoc: number | null;
    rivalErsMode: ErsMode | null;
    pLderate: number | null;
    pLharvest: number | null;
    pOtAvail: number | null;
    trapFlag: boolean;
    trapProbability: number | null;
    hmmBelief?: HmmBeliefState | undefined;
    provenance: Provenance;
  };

  // E. PASS MODEL
  passModel?: {
    features: PassModelFeatures;
    pPass: number;
    modelProvenance: "HEURISTIC" | "TRAINED_ML";
  } | undefined;

  // F. OVERTAKE EV
  overtakeEv?: {
    breakdown: OvertakeEvBreakdown;
    strategicEv: number;
    recommendation: Posture;
  } | undefined;

  // G. WHAT-IF
  whatIfBranches?: Record<Posture, RaceIQWhatIfBranch> | undefined;

  // H. TIMELINES
  timelines: {
    socOverTime: { lap: number; time: number; soc: number }[];
    ersModeOverTime: { lap: number; time: number; mode: ErsMode }[];
    clippingEventsOverTime: { lap: number; time: number; clipping: boolean }[];
    gapOverTime: { lap: number; time: number; gapAhead: number | null; gapToLeader: number | null }[];
    pPassOverTime: { lap: number; time: number; pPass: number }[];
    strategicEvOverTime: { lap: number; time: number; ev: number }[];
    recommendationOverTime: { lap: number; time: number; posture: Posture }[];
    hmmProbabilitiesOverTime: {
      lap: number;
      time: number;
      pLderate: number;
      pLharvest: number;
      pOtAvail: number;
    }[];
    history: TimelineSample[];
  };
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
  hmmBelief?: HmmBeliefState | undefined;
  passFeatures?: PassModelFeatures | undefined;
  evBreakdown?: OvertakeEvBreakdown | undefined;
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
  /** Analysis snapshot exposing the complete data provenance, HMM belief, PassModel features, EV, and timelines. */
  analysisSnapshotAt?: (
    circuitId: string,
    time: number,
    code: string,
  ) => RaceIQAnalysisSnapshot | undefined;
}

export function driverStateOf(
  snapshot: RaceIQSnapshot,
  code: string,
): RaceIQDriverState | undefined {
  return snapshot.byCode[code];
}
