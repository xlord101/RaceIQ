import type {
  Posture,
  RaceIQDriverState,
  RaceIQRecommendation,
  RaceIQSnapshot,
  RaceIQWhatIfBranch,
} from "./contracts";

export type { Posture };
export type Recommendation = RaceIQRecommendation;
export type WhatIfBranch = RaceIQWhatIfBranch;

/**
 * Placeholder posture policy shipped with the simulation adapter. Logic is
 * unchanged; it simply reads the optional contract fields defensively so a real
 * adapter with partial data cannot crash the UI.
 */
export function recommend(
  snapshot: RaceIQSnapshot,
  code: string,
): Recommendation | undefined {
  const self = snapshot.byCode[code];
  if (!self) return undefined;
  const ahead = snapshot.drivers.find((d) => d.position === self.position - 1);
  const behind = snapshot.drivers.find((d) => d.position === self.position + 1);

  const selfSoc = self.soc ?? 0.5;
  const gapAhead = ahead ? (self.gapAhead ?? 99) : 99;
  const gapBehind = behind ? (behind.gapAhead ?? 99) : 99;
  const socEdgeAhead = ahead && typeof ahead.soc === "number" ? selfSoc - ahead.soc : 0.2;
  const socEdgeBehind = behind && typeof behind.soc === "number" ? selfSoc - behind.soc : 0.2;

  const passProbability = clamp(
    0.5 + socEdgeAhead * 0.9 - (gapAhead - 0.7) * 0.28 + (self.inDetectionWindow ? 0.08 : 0),
    0.03,
    0.94,
  );
  const energyCost = clamp(0.06 + gapAhead * 0.02, 0.04, 0.22);
  const overtakeEv = passProbability * 1.9 - (1 - passProbability) * 1.1 - energyCost * 3;

  let posture: Posture;
  let headline: string;
  let reason: string;

  if (selfSoc < 0.25) {
    posture = "HARVEST";
    headline = "Rebuild energy now";
    reason = `Estimated battery is low (${pct(selfSoc)}). Recharging for two laps protects the next attack window.`;
  } else if (gapAhead < 1.4 && overtakeEv > 0.2 && selfSoc > 0.45) {
    posture = "ATTACK";
    headline = `Attack ${ahead?.code ?? ""}`.trim();
    reason = `Inside the detection gap at ${gapAhead.toFixed(2)}s with a ${pctPoints(socEdgeAhead)} energy edge — worth spending Overtake Mode.`;
  } else if (gapBehind < 1.0 && socEdgeBehind < 0) {
    posture = "DEFEND";
    headline = `Cover ${behind?.code ?? "the car behind"}`;
    reason = `Car behind is ${gapBehind.toFixed(2)}s back with more energy. Hold the racing line and keep deploy in reserve.`;
  } else {
    posture = "HOLD";
    headline = "Hold position";
    reason = `Nothing in range: ${gapAhead.toFixed(1)}s ahead, ${gapBehind.toFixed(1)}s behind. Bank energy and keep the tyre alive.`;
  }

  const confidence = clamp(
    0.82 - Math.abs(0.5 - passProbability) * 0.15 - (self.ersMode === "CLIPPING" ? 0.1 : 0),
    0.4,
    0.93,
  );

  return {
    posture,
    headline,
    reason,
    confidence,
    passProbability,
    overtakeEv,
    energyCost,
    constraints: [
      "Overtake Mode only between the Overtake Detection Line and Overtake Activation Line",
      "Active Aero Straight Mode limited to designated straight-mode zones",
      "Per-lap deploy allocation must stay inside the regulated energy budget",
    ],
    factors: [
      { label: "Position", value: `P${self.position}`, provenance: snapshot.positionsProvenance },
      { label: "Gap ahead", value: `${gapAhead.toFixed(2)}s`, provenance: snapshot.positionsProvenance },
      { label: "Estimated SoC", value: pct(selfSoc), provenance: snapshot.energyProvenance },
      { label: "ERS state", value: self.ersMode ?? "—", provenance: snapshot.energyProvenance },
      { label: "Active Aero", value: self.aeroMode ? `${self.aeroMode} MODE` : "—", provenance: "INFERRED" },
      { label: "P(pass)", value: pct(passProbability), provenance: "INFERRED" },
      { label: "Overtake EV", value: `${overtakeEv >= 0 ? "+" : ""}${overtakeEv.toFixed(2)}s`, provenance: "INFERRED" },
    ],
  };
}

/** Builds a counterfactual branch from an immutable snapshot seed. History is never mutated. */
export function simulateWhatIf(
  snapshot: RaceIQSnapshot,
  code: string,
  action: Posture,
): WhatIfBranch | undefined {
  const self: RaceIQDriverState | undefined = snapshot.byCode[code];
  const rec = recommend(snapshot, code);
  if (!self || !rec) return undefined;
  const ahead = snapshot.drivers.find((d) => d.position === self.position - 1);
  const selfSoc = self.soc ?? 0.5;
  const selfGap = self.gapAhead ?? 0;
  const energyCost = rec.energyCost ?? 0.08;
  const seed = {
    ...snapshot.session,
    driver: code,
    position: self.position,
    gapAhead: self.gapAhead,
    soc: self.soc,
  };

  if (action === "ATTACK") {
    const success = (rec.passProbability ?? 0) > 0.5;
    return {
      seed,
      action,
      projectedPosition: success ? Math.max(1, self.position - 1) : self.position,
      projectedGap: success ? 0.9 : Math.max(0.2, selfGap - 0.3),
      projectedSoc: clamp(selfSoc - energyCost, 0.03, 1),
      energyCost,
      outcome: success
        ? `Projected move on ${ahead?.code ?? "the car ahead"} completes before the Overtake Activation Line.`
        : `Projected attempt falls short; ${ahead?.code ?? "the car ahead"} holds the inside line and both cars lose time.`,
      risk: (rec.passProbability ?? 0) > 0.6 ? "MEDIUM" : "HIGH",
      confidence: rec.confidence,
      opponentResponse: "Likely counter: opponent switches to Straight Mode early and covers the inside.",
    };
  }
  if (action === "DEFEND") {
    return {
      seed,
      action,
      projectedPosition: self.position,
      projectedGap: clamp(selfGap + 0.4, 0, 30),
      projectedSoc: clamp(selfSoc - 0.04, 0.03, 1),
      energyCost: 0.04,
      outcome: "Projected position held; small time loss from defensive lines.",
      risk: "LOW",
      confidence: clamp((rec.confidence ?? 0.6) + 0.05, 0, 0.95),
      opponentResponse: "Likely counter: car behind backs out and resets for the next lap.",
    };
  }
  if (action === "HARVEST") {
    return {
      seed,
      action,
      projectedPosition: Math.min(snapshot.drivers.length, self.position + 1),
      projectedGap: clamp(selfGap + 1.6, 0, 40),
      projectedSoc: clamp(selfSoc + 0.18, 0, 1),
      energyCost: -0.18,
      outcome: "Projected loss of one place now, with a full deploy window available two laps later.",
      risk: "LOW",
      confidence: clamp((rec.confidence ?? 0.6) + 0.03, 0, 0.95),
      opponentResponse: "Likely counter: opponent takes the place cheaply and defends later.",
    };
  }
  return {
    seed,
    action,
    projectedPosition: self.position,
    projectedGap: clamp(selfGap + 0.2, 0, 40),
    projectedSoc: clamp(selfSoc + 0.05, 0, 1),
    energyCost: -0.05,
    outcome: "Projected stable stint: position kept, energy slightly rebuilt.",
    risk: "LOW",
    confidence: rec.confidence,
    opponentResponse: "Likely counter: no change in opponent behaviour.",
  };
}

export function clamp(v: number, lo: number, hi: number) {
  return Math.min(hi, Math.max(lo, v));
}
export function pct(v: number) {
  return `${Math.round(v * 100)}%`;
}
export function pctPoints(v: number) {
  return `${v >= 0 ? "+" : ""}${Math.round(v * 100)} pt`;
}
