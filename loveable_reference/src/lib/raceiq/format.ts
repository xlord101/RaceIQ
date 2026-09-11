/**
 * Display helpers. Every value the UI shows passes through here so a missing
 * backend field renders as a neutral placeholder instead of a fabricated number.
 */

export const EMPTY = "—";

export function isNum(v: number | undefined | null): v is number {
  return typeof v === "number" && Number.isFinite(v);
}

/** 0..1 → "63%" */
export function fmtPct(v?: number, fallback = EMPTY) {
  return isNum(v) ? `${Math.round(v * 100)}%` : fallback;
}

/** 0..1 → 63 (for bar widths); undefined → 0 */
export function pctWidth(v?: number) {
  return isNum(v) ? Math.max(0, Math.min(100, Math.round(v * 100))) : 0;
}

/** 0..1 → "+8 pt" */
export function fmtPoints(v?: number, fallback = EMPTY) {
  if (!isNum(v)) return fallback;
  const pts = Math.round(v * 100);
  return `${pts >= 0 ? "+" : ""}${pts} pt`;
}

export function fmtSeconds(v?: number, digits = 1, fallback = EMPTY) {
  return isNum(v) ? `${v.toFixed(digits)}s` : fallback;
}

export function fmtSignedSeconds(v?: number, digits = 2, fallback = EMPTY) {
  return isNum(v) ? `${v >= 0 ? "+" : ""}${v.toFixed(digits)}s` : fallback;
}

/** Gap behind another car: "+0.72s", or a leader/empty marker. */
export function fmtGap(v?: number, digits = 1, fallback = EMPTY) {
  return isNum(v) ? `+${v.toFixed(digits)}s` : fallback;
}

export function fmtClock(seconds?: number, fallback = EMPTY) {
  if (!isNum(seconds)) return fallback;
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  return `${m}:${s.toString().padStart(2, "0")}`;
}

export function fmtPosition(position?: number, fallback = EMPTY) {
  return typeof position === "number" ? `P${position}` : fallback;
}
