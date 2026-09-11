import { TRACK_PATHS } from "./trackPaths";

export type CircuitId = "melbourne" | "shanghai" | "monza";

export interface BrakingZone {
  /** Approximate normalized lap position; presentation guide, not telemetry. */
  at: number;
  width: number;
  label: string;
}

export interface Circuit {
  id: CircuitId;
  name: string;
  event: string;
  country: string;
  laps: number;
  baseLapTime: number; // seconds
  /** Current-layout circuit centerline used by the replay map. */
  path: string;
  viewBox: string;
  /** Fractions of a lap where the schematic sector boundaries sit. */
  sectors: [number, number];
  /** Fraction of the lap where the Overtake Detection Line sits. */
  detectionLine: number;
  /** Fraction of the lap where the Overtake Activation Line sits. */
  activationLine: number;
  /** Major braking areas shown as contextual track overlays. */
  brakingZones: BrakingZone[];
}

export const CIRCUITS: Record<CircuitId, Circuit> = {
  melbourne: {
    id: "melbourne",
    name: "Albert Park",
    event: "Melbourne",
    country: "Australia",
    laps: 24,
    baseLapTime: 80,
    viewBox: "0 0 500 500",
    path: TRACK_PATHS.melbourne,
    sectors: [0.34, 0.68],
    detectionLine: 0.52,
    activationLine: 0.63,
    brakingZones: [
      { at: 0.03, width: 0.035, label: "T1" },
      { at: 0.14, width: 0.032, label: "T3" },
      { at: 0.3, width: 0.03, label: "T6" },
      { at: 0.56, width: 0.034, label: "T9–10" },
      { at: 0.68, width: 0.03, label: "T11" },
      { at: 0.85, width: 0.034, label: "T13" },
    ],
  },
  shanghai: {
    id: "shanghai",
    name: "Shanghai International",
    event: "Shanghai",
    country: "China",
    laps: 22,
    baseLapTime: 94,
    viewBox: "0 0 500 500",
    path: TRACK_PATHS.shanghai,
    sectors: [0.3, 0.66],
    detectionLine: 0.74,
    activationLine: 0.88,
    brakingZones: [
      { at: 0.05, width: 0.05, label: "T1–3" },
      { at: 0.35, width: 0.038, label: "T6" },
      { at: 0.55, width: 0.032, label: "T11" },
      { at: 0.85, width: 0.05, label: "T14" },
    ],
  },
  monza: {
    id: "monza",
    name: "Monza",
    event: "Monza",
    country: "Italy",
    laps: 26,
    baseLapTime: 82,
    viewBox: "0 0 500 500",
    path: TRACK_PATHS.monza,
    sectors: [0.28, 0.62],
    detectionLine: 0.8,
    activationLine: 0.94,
    brakingZones: [
      { at: 0.06, width: 0.05, label: "T1 · Rettifilo" },
      { at: 0.3, width: 0.04, label: "T4 · Roggia" },
      { at: 0.47, width: 0.04, label: "T6–7 · Lesmo" },
      { at: 0.72, width: 0.05, label: "T8–10 · Ascari" },
      { at: 0.92, width: 0.045, label: "T11 · Alboreto" },
    ],
  },
};

export const CIRCUIT_LIST = [CIRCUITS.melbourne, CIRCUITS.shanghai, CIRCUITS.monza];
