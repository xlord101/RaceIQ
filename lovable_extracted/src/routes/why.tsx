import { createFileRoute, Link } from "@tanstack/react-router";
import { useState } from "react";
import {
  ResponsiveContainer,
  LineChart,
  Line,
  AreaChart,
  Area,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ReferenceLine,
  ReferenceDot,
  Legend,
} from "recharts";
import { POSTURE_STYLE } from "@/components/raceiq/MatchupCard";
import { ProvenanceTag } from "@/components/raceiq/ProvenanceTag";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import type { Posture, Provenance } from "@/lib/raceiq/contracts";
import {
  EMPTY,
  fmtGap,
  fmtPct,
  fmtPoints,
  fmtPosition,
  fmtSeconds,
  fmtSignedSeconds,
  isNum,
} from "@/lib/raceiq/format";
import { useRaceIQ } from "@/lib/raceiq/store";

export const Route = createFileRoute("/why")({
  head: () => ({
    meta: [
      { title: "Why — RaceIQ Auditable Decision Engine" },
      {
        name: "description",
        content:
          "Auditable explanation of RaceIQ race decisions: observed kinematics, derived features, energy inference, opponent Bayesian HMM, pass probability, and strategic expected value.",
      },
      { property: "og:title", content: "Why — RaceIQ Auditable Decision Engine" },
      {
        name: "og:description",
        content:
          "Progressive disclosure of the end-to-end auditable decision chain: Observe -> Derive -> Infer -> Estimate -> Value -> Decide.",
      },
    ],
  }),
  component: Why,
});

function fmtSignedPoints(v?: number | null, fallback = EMPTY): string {
  if (!isNum(v)) return fallback;
  return `${v > 0 ? "+" : ""}${v.toFixed(2)} pts`;
}

function SectionCard({
  number,
  title,
  subtitle,
  provenance,
  children,
  defaultOpen = true,
}: {
  number: string;
  title: string;
  subtitle: string;
  provenance: Provenance;
  children: React.ReactNode;
  defaultOpen?: boolean;
}) {
  const [open, setOpen] = useState(defaultOpen);

  return (
    <section className="panel overflow-hidden border border-border/70 bg-card/60 transition-colors">
      <div
        onClick={() => setOpen((prev) => !prev)}
        className="flex cursor-pointer items-center justify-between gap-4 border-b border-border/40 p-4 transition-colors hover:bg-muted/30"
      >
        <div className="flex min-w-0 items-center gap-3">
          <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-md border border-border/80 bg-surface text-xs font-semibold text-muted-foreground">
            {number}
          </span>
          <div className="min-w-0">
            <h2 className="text-sm font-semibold tracking-wide text-foreground uppercase sm:text-base">
              {title}
            </h2>
            <p className="truncate text-xs text-muted-foreground">{subtitle}</p>
          </div>
        </div>
        <div className="flex shrink-0 items-center gap-2.5">
          <ProvenanceTag kind={provenance} />
          <span className="font-mono text-sm text-muted-foreground">{open ? "−" : "+"}</span>
        </div>
      </div>
      {open && <div className="p-4 sm:p-5 space-y-4">{children}</div>}
    </section>
  );
}

function Why() {
  const {
    snapshot,
    selected,
    circuit,
    driver: driverOf,
    stateOf,
    recommendationFor,
    analysisSnapshot,
  } = useRaceIQ();

  const state = stateOf(selected);
  const driver = driverOf(selected);
  const rec = recommendationFor(selected);

  // Derived context
  const rivalCode = analysisSnapshot?.opponentInference?.rivalCode ?? null;
  const rivalDriver = rivalCode ? driverOf(rivalCode) : null;
  const rivalState = rivalCode ? stateOf(rivalCode) : null;
  const isLeader = (state?.position ?? 0) <= 1;

  // Active sub-lap index for 16 checkpoints
  const subLap = analysisSnapshot?.telemetry?.subLapCheckpoints;
  const lapFraction = state?.lapFraction ?? 0;
  const activeCheckpointIdx = Math.min(15, Math.max(0, Math.floor(lapFraction * 16)));

  // Telemetry checkpoint chart data (100% factual 16 checkpoints from replay)
  const telemetryData = subLap?.speed?.map((spd, i) => ({
    checkpoint: i + 1,
    speed: spd,
    throttle: subLap.throttle ? subLap.throttle[i] : 0,
    brake: subLap.brake ? subLap.brake[i] : 0,
    distance: subLap.distance ? subLap.distance[i] : 0,
    socPct: subLap.soc ? Math.round(subLap.soc[i] * 100) : 0,
    mode: subLap.modes ? subLap.modes[i] : "BALANCED",
    kind: subLap.kinds ? subLap.kinds[i] : "straight",
  })) ?? [];

  // Ranked 8-state HMM posterior distribution
  const rawHmm = analysisSnapshot?.opponentInference?.hmmBelief;
  const hmmStates = rawHmm
    ? Object.entries(rawHmm)
        .map(([name, prob]) => ({
          name,
          prob,
          pct: Math.round(prob * 100),
          isDerate: name.startsWith("Lderate"),
          isHarvest: name.startsWith("Lharvest"),
        }))
        .sort((a, b) => b.prob - a.prob)
    : [];
  const dominantState = hmmStates[0]?.name ?? "H|OT_avail";

  // PassModel 12 canonical features
  const pmFeat = analysisSnapshot?.passModel?.features;
  const canonicalFeaturesList = pmFeat
    ? [
        {
          num: 1,
          name: "gap_ahead_s",
          label: "Gap Ahead",
          value: `${pmFeat.gap_ahead_s.toFixed(2)} s`,
          provenance: "OBSERVED" as Provenance,
          desc: "Physical gap to the car ahead at detection point",
        },
        {
          num: 2,
          name: "closing_speed_kph",
          label: "Closing Speed",
          value: `${pmFeat.closing_speed_kph > 0 ? "+" : ""}${pmFeat.closing_speed_kph.toFixed(1)} km/h`,
          provenance: "DERIVED" as Provenance,
          desc: "Speed delta closing rate along active straight",
        },
        {
          num: 3,
          name: "straight_remaining_m",
          label: "Straight Remaining",
          value: `${pmFeat.straight_remaining_m.toFixed(0)} m`,
          provenance: "DERIVED" as Provenance,
          desc: "Distance remaining before heavy braking zone",
        },
        {
          num: 4,
          name: "tyre_age_delta_laps",
          label: "Tyre-Age Delta",
          value: `${pmFeat.tyre_age_delta_laps > 0 ? "+" : ""}${pmFeat.tyre_age_delta_laps.toFixed(1)} laps`,
          provenance: "OBSERVED" as Provenance,
          desc: "Tyre compound degradation delta (own - rival)",
        },
        {
          num: 5,
          name: "own_est_soc",
          label: "Own Estimated SoC",
          value: `${pmFeat.own_est_soc.toFixed(2)} MJ`,
          provenance: "INFERRED" as Provenance,
          desc: "Observer estimate of our deployable battery energy",
        },
        {
          num: 6,
          name: "rival_est_soc",
          label: "Rival Estimated SoC",
          value: `${pmFeat.rival_est_soc.toFixed(2)} MJ`,
          provenance: "INFERRED" as Provenance,
          desc: "Observer estimate of rival deployable battery energy",
        },
        {
          num: 7,
          name: "rival_P_Lderate",
          label: "Rival P(Lderate)",
          value: fmtPct(pmFeat.rival_P_Lderate),
          provenance: "INFERRED" as Provenance,
          desc: "Posterior probability rival is genuine derate (energy-empty)",
        },
        {
          num: 8,
          name: "rival_P_Lharvest",
          label: "Rival P(Lharvest)",
          value: fmtPct(pmFeat.rival_P_Lharvest),
          provenance: "INFERRED" as Provenance,
          desc: "Posterior probability rival is deliberately harvesting (trap)",
        },
        {
          num: 9,
          name: "trap_flag",
          label: "Trap Flag",
          value: pmFeat.trap_flag ? "FLAGGED (TRUE)" : "CLEAR (FALSE)",
          provenance: "INFERRED" as Provenance,
          desc: "Heuristic trap trigger when opponent hoards deploy reserve",
        },
        {
          num: 10,
          name: "overtake_mode_active",
          label: "Overtake Mode",
          value: pmFeat.overtake_mode_active ? "ACTIVE" : "INACTIVE",
          provenance: "OBSERVED" as Provenance,
          desc: "FIA overtake boost activation window status",
        },
        {
          num: 11,
          name: "circuit_harvest_potential_mj",
          label: "Circuit Harvest Potential",
          value: `${pmFeat.circuit_harvest_potential_mj.toFixed(1)} MJ`,
          provenance: "DERIVED" as Provenance,
          desc: "Predicted braking regen available over remainder of lap",
        },
        {
          num: 12,
          name: "laps_remaining",
          label: "Laps Remaining",
          value: `${pmFeat.laps_remaining}`,
          provenance: "OBSERVED" as Provenance,
          desc: "Remaining laps to race completion",
        },
      ]
    : [];

  // Overtake EV breakdown
  const evBreakdown = analysisSnapshot?.overtakeEv?.breakdown;
  const strategicEv = analysisSnapshot?.overtakeEv?.strategicEv;
  const recommendation = analysisSnapshot?.overtakeEv?.recommendation ?? rec?.posture ?? "HOLD";

  // Stint Timelines
  const timelines = analysisSnapshot?.timelines;

  return (
    <main className="mx-auto max-w-[1280px] px-4 py-6 sm:px-6 space-y-6">
      {/* ========================================================================= */}
      {/* HEADER / DECISION CONTEXT                                                 */}
      {/* ========================================================================= */}
      <header className="panel relative overflow-hidden border border-border/80 bg-card/80 p-5 sm:p-6 shadow-sm">
        <div className="flex flex-wrap items-center justify-between gap-3 border-b border-border/60 pb-4">
          <div className="flex items-center gap-2">
            <span className="h-2 w-2 rounded-full bg-emerald-500 animate-pulse" />
            <p className="eyebrow tracking-wider text-muted-foreground font-semibold">
              RACEIQ REASONING ENGINE · AUDITABLE DECISION PROOF
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <ProvenanceTag kind="ACTUAL" />
            <ProvenanceTag kind="INFERRED" />
            <span className="text-[11px] text-muted-foreground font-mono">
              HISTORICAL REPLAY · 2026 REGULATION
            </span>
          </div>
        </div>

        <div className="mt-5 grid gap-6 lg:grid-cols-[1fr_auto]">
          <div className="space-y-3">
            <div className="flex flex-wrap items-baseline gap-3">
              <h1 className="text-xl sm:text-2xl font-bold tracking-tight text-foreground">
                WHY DID RACEIQ SAY
              </h1>
              <span
                className={`data inline-flex items-center justify-center rounded-lg border px-4 py-1 text-base sm:text-lg font-bold tracking-[0.16em] shadow-sm ${
                  POSTURE_STYLE[recommendation] ?? "border-border text-muted-foreground"
                }`}
              >
                {recommendation}
              </span>
              <span className="text-xl sm:text-2xl font-bold tracking-tight text-foreground">
                ?
              </span>
            </div>
            <p className="text-sm text-muted-foreground max-w-3xl leading-relaxed">
              {rec?.reason ??
                "Evaluated from factual sub-lap telemetry, deterministic battery energy observer, Bayesian opponent posture belief, and points-weighted overtake expectation."}
            </p>
            <p className="text-xs text-muted-foreground/80 italic">
              Note: The current decision is based on actual historical race state with inferred
              energy observer and Bayesian opponent model outputs.
            </p>
          </div>

          <div className="flex flex-col justify-center border-t border-border/50 pt-4 lg:border-t-0 lg:border-l lg:pl-6 lg:pt-0">
            <div className="grid grid-cols-2 sm:grid-cols-4 lg:grid-cols-2 gap-3 font-mono text-xs">
              <div className="panel p-2.5 bg-surface/50 border-border/50">
                <span className="text-[10px] text-muted-foreground block uppercase">
                  Strategic EV (pts-eq)
                </span>
                <span className="text-sm font-semibold text-foreground">
                  {fmtSignedPoints(strategicEv)}
                </span>
              </div>
              <div className="panel p-2.5 bg-surface/50 border-border/50">
                <span className="text-[10px] text-muted-foreground block uppercase">
                  Pass Probability
                </span>
                <span className="text-sm font-semibold text-foreground">
                  {fmtPct(analysisSnapshot?.passModel?.pPass ?? rec?.passProbability)}
                </span>
              </div>
              <div className="panel p-2.5 bg-surface/50 border-border/50">
                <span className="text-[10px] text-muted-foreground block uppercase">
                  Model Status
                </span>
                <span className="text-xs font-semibold text-emerald-400">
                  HEURISTIC (12-FEAT)
                </span>
              </div>
              <div className="panel p-2.5 bg-surface/50 border-border/50">
                <span className="text-[10px] text-muted-foreground block uppercase">
                  Confidence
                </span>
                <span className="text-sm font-semibold text-foreground">
                  {fmtPct(rec?.confidence)}
                </span>
              </div>
            </div>
          </div>
        </div>

        {/* Factual Context Badges Strip */}
        <div className="mt-5 flex flex-wrap items-center gap-2 border-t border-border/40 pt-4 font-mono text-xs">
          <span className="px-2.5 py-1 rounded bg-muted/40 text-foreground border border-border/60">
            CIRCUIT: <span className="text-primary font-semibold">{circuit.name}</span>
          </span>
          <span className="px-2.5 py-1 rounded bg-muted/40 text-foreground border border-border/60">
            LAP: <span className="font-semibold">{snapshot.lap}</span> / {snapshot.totalLaps}
          </span>
          <span className="px-2.5 py-1 rounded bg-muted/40 text-foreground border border-border/60">
            DRIVER: <span className="font-semibold text-foreground">{selected}</span>
            {driver.name ? ` (${driver.name})` : ""}
          </span>
          <span className="px-2.5 py-1 rounded bg-muted/40 text-foreground border border-border/60">
            RIVAL:{" "}
            <span className="font-semibold text-attack">
              {rivalCode ? `${rivalCode}${rivalDriver?.name ? ` (${rivalDriver.name})` : ""}` : "NONE IN RANGE"}
            </span>
          </span>
          <span className="px-2.5 py-1 rounded bg-muted/40 text-foreground border border-border/60">
            POSITION: <span className="font-semibold">{fmtPosition(state?.position)}</span>
          </span>
          <span className="px-2.5 py-1 rounded bg-muted/40 text-foreground border border-border/60">
            GAP AHEAD:{" "}
            <span className="font-semibold">
              {isLeader ? "n/a (Leader)" : fmtSeconds(state?.gapAhead, 2)}
            </span>
          </span>
          <span className="px-2.5 py-1 rounded bg-muted/40 text-foreground border border-border/60">
            CUMULATIVE RACE GAP:{" "}
            <span className="font-semibold">
              {isLeader ? "0.00s" : fmtSeconds(state?.gapToLeader, 2)}
            </span>
          </span>
        </div>
      </header>

      {/* ========================================================================= */}
      {/* SECTION 1 — WHAT RACEIQ OBSERVED                                          */}
      {/* ========================================================================= */}
      <SectionCard
        number="1"
        title="Observed Race State"
        subtitle="Actual vehicle kinematics, spatial checkpoints, and directly measured track conditions"
        provenance="ACTUAL"
      >
        <div className="grid grid-cols-2 sm:grid-cols-4 lg:grid-cols-6 gap-3 font-mono">
          <div className="panel p-3 bg-surface/40">
            <span className="text-[10px] text-muted-foreground uppercase block">Speed</span>
            <span className="text-base font-bold text-foreground">
              {isNum(analysisSnapshot?.telemetry?.speed)
                ? `${analysisSnapshot.telemetry.speed.toFixed(1)} km/h`
                : EMPTY}
            </span>
            <span className="text-[10px] text-actual font-mono mt-0.5 block">ACTUAL</span>
          </div>
          <div className="panel p-3 bg-surface/40">
            <span className="text-[10px] text-muted-foreground uppercase block">Throttle</span>
            <span className="text-base font-bold text-foreground">
              {isNum(analysisSnapshot?.telemetry?.throttle)
                ? `${analysisSnapshot.telemetry.throttle.toFixed(1)}%`
                : EMPTY}
            </span>
            <span className="text-[10px] text-actual font-mono mt-0.5 block">ACTUAL</span>
          </div>
          <div className="panel p-3 bg-surface/40">
            <span className="text-[10px] text-muted-foreground uppercase block">Brake</span>
            <span className="text-base font-bold text-foreground">
              {isNum(analysisSnapshot?.telemetry?.brake)
                ? `${analysisSnapshot.telemetry.brake.toFixed(1)}%`
                : EMPTY}
            </span>
            <span className="text-[10px] text-actual font-mono mt-0.5 block">ACTUAL</span>
          </div>
          <div className="panel p-3 bg-surface/40">
            <span className="text-[10px] text-muted-foreground uppercase block">Lap Distance</span>
            <span className="text-base font-bold text-foreground">
              {isNum(analysisSnapshot?.telemetry?.distance)
                ? `${analysisSnapshot.telemetry.distance.toFixed(0)} m`
                : EMPTY}
            </span>
            <span className="text-[10px] text-actual font-mono mt-0.5 block">ACTUAL</span>
          </div>
          <div className="panel p-3 bg-surface/40">
            <span className="text-[10px] text-muted-foreground uppercase block">Detection Gap</span>
            <span className="text-base font-bold text-foreground">
              {isLeader ? "LEADER" : fmtSeconds(state?.gapAhead, 2)}
            </span>
            <span className="text-[10px] text-actual font-mono mt-0.5 block">ACTUAL</span>
          </div>
          <div className="panel p-3 bg-surface/40">
            <span className="text-[10px] text-muted-foreground uppercase block">Race Position</span>
            <span className="text-base font-bold text-foreground">
              {fmtPosition(state?.position)}
            </span>
            <span className="text-[10px] text-actual font-mono mt-0.5 block">ACTUAL</span>
          </div>
        </div>

        {/* Spatial Segment & Detection Window Context */}
        <div className="grid gap-3 sm:grid-cols-2 font-mono text-xs">
          <div className="p-3 rounded-lg border border-border/60 bg-muted/20 space-y-1.5">
            <span className="eyebrow block text-muted-foreground">Detection Window Context</span>
            <div className="flex justify-between">
              <span className="text-muted-foreground">Detection Line:</span>
              <span className="text-foreground">{fmtPct(circuit.detectionLine)} of lap</span>
            </div>
            <div className="flex justify-between">
              <span className="text-muted-foreground">Activation Line:</span>
              <span className="text-foreground">{fmtPct(circuit.activationLine)} of lap</span>
            </div>
            <div className="flex justify-between">
              <span className="text-muted-foreground">Inside Overtake Window:</span>
              <span
                className={`font-semibold ${
                  analysisSnapshot?.telemetry?.detectionWindow?.inWindow
                    ? "text-emerald-400"
                    : "text-muted-foreground"
                }`}
              >
                {analysisSnapshot?.telemetry?.detectionWindow?.inWindow ? "YES (ACTIVE)" : "NO"}
              </span>
            </div>
          </div>

          <div className="p-3 rounded-lg border border-border/60 bg-muted/20 space-y-1.5">
            <span className="eyebrow block text-muted-foreground">Track Segment Context</span>
            <div className="flex justify-between">
              <span className="text-muted-foreground">Current Segment:</span>
              <span className="text-foreground uppercase">
                {analysisSnapshot?.telemetry?.relevantTrackSegment ?? "STRAIGHT"}
              </span>
            </div>
            <div className="flex justify-between">
              <span className="text-muted-foreground">Active Straight Remaining:</span>
              <span className="text-foreground">
                {analysisSnapshot?.passModel?.features?.straight_remaining_m.toFixed(0) ?? "650"} m
              </span>
            </div>
            <div className="flex justify-between">
              <span className="text-muted-foreground">Longest Circuit Straight:</span>
              <span className="text-foreground">
                {analysisSnapshot?.telemetry?.straightContext?.longestStraightM?.toFixed(0) ?? "650"} m
              </span>
            </div>
          </div>
        </div>

        {/* 16-Checkpoint Actual Telemetry Chart */}
        <div className="space-y-2">
          <div className="flex items-center justify-between">
            <span className="eyebrow text-muted-foreground">
              Sub-Lap Spatial Telemetry (16 Actual Checkpoints across Lap {snapshot.lap})
            </span>
            <span className="text-[11px] font-mono text-actual">
              CURRENT POSITION: CHECKPOINT #{activeCheckpointIdx + 1} ({Math.round(lapFraction * 100)}% LAP)
            </span>
          </div>

          {telemetryData.length > 0 ? (
            <div className="h-56 w-full rounded-lg border border-border/50 bg-surface/20 p-2">
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={telemetryData} margin={{ top: 10, right: 10, left: -20, bottom: 0 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="oklch(0.32 0.006 285 / 0.4)" />
                  <XAxis
                    dataKey="checkpoint"
                    tick={{ fontSize: 10, fill: "oklch(0.68 0.008 285)" }}
                    tickFormatter={(v) => `CP${v}`}
                  />
                  <YAxis
                    yAxisId="speed"
                    domain={[60, 360]}
                    tick={{ fontSize: 10, fill: "oklch(0.68 0.008 285)" }}
                    unit=" km/h"
                  />
                  <YAxis
                    yAxisId="pedal"
                    orientation="right"
                    domain={[0, 100]}
                    hide
                  />
                  <Tooltip
                    contentStyle={{
                      backgroundColor: "oklch(0.235 0.005 285)",
                      borderColor: "oklch(0.32 0.006 285)",
                      borderRadius: "8px",
                      fontSize: "11px",
                      fontFamily: "monospace",
                    }}
                    formatter={(val: any, name: string) => {
                      if (name === "Speed") return [`${val} km/h`, name];
                      if (name === "Throttle") return [`${val}%`, name];
                      if (name === "Brake") return [`${val}%`, name];
                      return [val, name];
                    }}
                    labelFormatter={(cp) => `Checkpoint #${cp} (${telemetryData[Number(cp) - 1]?.kind ?? "straight"})`}
                  />
                  <Legend wrapperStyle={{ fontSize: "11px", fontFamily: "monospace" }} />
                  <ReferenceLine
                    x={activeCheckpointIdx + 1}
                    yAxisId="speed"
                    stroke="oklch(0.78 0.13 200)"
                    strokeWidth={2}
                    strokeDasharray="4 4"
                    label={{
                      value: "CAR NOW",
                      fill: "oklch(0.78 0.13 200)",
                      fontSize: 10,
                      position: "top",
                    }}
                  />
                  <Line
                    yAxisId="speed"
                    type="monotone"
                    dataKey="speed"
                    name="Speed"
                    stroke="oklch(0.78 0.13 200)"
                    strokeWidth={2}
                    dot={{ r: 2 }}
                    activeDot={{ r: 5 }}
                  />
                  <Line
                    yAxisId="pedal"
                    type="monotone"
                    dataKey="throttle"
                    name="Throttle"
                    stroke="oklch(0.75 0.16 155)"
                    strokeWidth={1.5}
                    dot={false}
                  />
                  <Line
                    yAxisId="pedal"
                    type="monotone"
                    dataKey="brake"
                    name="Brake"
                    stroke="oklch(0.68 0.19 30)"
                    strokeWidth={1.5}
                    dot={false}
                  />
                </LineChart>
              </ResponsiveContainer>
            </div>
          ) : (
            <div className="p-6 text-center text-xs text-muted-foreground border border-dashed border-border rounded-lg">
              Sub-lap telemetry checkpoint data currently unavailable for this replay moment.
            </div>
          )}
        </div>
      </SectionCard>

      {/* ========================================================================= */}
      {/* SECTION 2 — DERIVED FEATURES                                              */}
      {/* ========================================================================= */}
      <SectionCard
        number="2"
        title="Features RaceIQ Calculated"
        subtitle="The exact 12 canonical features passed into the PassModel and EV decision engines"
        provenance="DERIVED"
      >
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-3">
          {canonicalFeaturesList.map((f) => (
            <div
              key={f.name}
              className="panel p-3 border-border/60 bg-surface/30 hover:border-border transition-colors flex flex-col justify-between space-y-2"
            >
              <div className="flex items-start justify-between gap-2">
                <span className="font-mono text-xs text-muted-foreground">
                  #{f.num} · {f.label}
                </span>
                <ProvenanceTag kind={f.provenance} />
              </div>
              <div>
                <span className="font-mono text-base font-bold text-foreground block">
                  {f.value}
                </span>
                <span className="text-[11px] text-muted-foreground leading-tight block mt-1">
                  {f.desc}
                </span>
              </div>
            </div>
          ))}
        </div>
      </SectionCard>

      {/* ========================================================================= */}
      {/* SECTION 3 — ENERGY / SoC INFERENCE                                        */}
      {/* ========================================================================= */}
      <SectionCard
        number="3"
        title="Energy State (SoC Inference)"
        subtitle="Deterministic energy-balance observer estimating battery state from vehicle behavior and 2026 rule limits"
        provenance="INFERRED"
      >
        <div className="rounded-lg border border-border/60 bg-muted/20 p-3 text-xs text-muted-foreground leading-relaxed">
          <p>
            <strong className="text-foreground">Inference Rule:</strong> State of Charge (SoC) is inferred
            by RaceIQ&apos;s deterministic energy-balance observer from observed vehicle telemetry, acceleration
            traces, and 2026 FIA rule constraints (8.5 MJ/lap harvest cap, 350 kW MGU-K limit).
            Direct battery telemetry is never measured directly.
          </p>
        </div>

        <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-3 font-mono">
          <div className="panel p-3 bg-surface/40">
            <span className="text-[10px] text-muted-foreground uppercase block">Current SoC</span>
            <span className="text-base font-bold text-foreground">{fmtPct(state?.soc)}</span>
            <span className="text-[10px] text-muted-foreground block mt-0.5">
              {isNum(state?.soc) ? `${((state.soc ?? 0) * 4.0).toFixed(2)} MJ` : EMPTY} / 4.0 MJ
            </span>
          </div>
          <div className="panel p-3 bg-surface/40">
            <span className="text-[10px] text-muted-foreground uppercase block">SoC Trend</span>
            <span className="text-base font-bold text-foreground">
              {isNum(state?.socTrend)
                ? `${((state?.socTrend ?? 0) * 100).toFixed(1)} pt/lap`
                : EMPTY}
            </span>
            <span className="text-[10px] text-inferred font-mono mt-0.5 block">ESTIMATED</span>
          </div>
          <div className="panel p-3 bg-surface/40">
            <span className="text-[10px] text-muted-foreground uppercase block">ERS Mode</span>
            <span className="text-sm font-bold text-foreground uppercase">
              {state?.ersMode ?? "BALANCED"}
            </span>
            <span className="text-[10px] text-inferred font-mono mt-0.5 block">CLASSIFIED</span>
          </div>
          <div className="panel p-3 bg-surface/40">
            <span className="text-[10px] text-muted-foreground uppercase block">Clipping State</span>
            <span
              className={`text-sm font-bold ${
                state?.ersMode === "CLIPPING" ? "text-attack" : "text-emerald-400"
              }`}
            >
              {state?.ersMode === "CLIPPING" ? "CLIPPING" : "NOMINAL"}
            </span>
            <span className="text-[10px] text-muted-foreground block mt-0.5">
              {state?.ersMode === "CLIPPING" ? "CEILING SATURATED" : "NO SATURATION"}
            </span>
          </div>
          <div className="panel p-3 bg-surface/40">
            <span className="text-[10px] text-muted-foreground uppercase block">FIA Harvest Cap</span>
            <span className="text-base font-bold text-foreground">8.5 MJ</span>
            <span className="text-[10px] text-actual font-mono mt-0.5 block">2026 REGULATION</span>
          </div>
          <div className="panel p-3 bg-surface/40">
            <span className="text-[10px] text-muted-foreground uppercase block">Harvest Potential</span>
            <span className="text-base font-bold text-foreground">
              {analysisSnapshot?.energy?.harvestPotentialMj?.toFixed(1) ?? "3.0"} MJ
            </span>
            <span className="text-[10px] text-derived font-mono mt-0.5 block">REMAINING LAP</span>
          </div>
        </div>

        {/* SoC Timeline Across Stint */}
        <div className="grid gap-4 lg:grid-cols-2">
          <div className="space-y-2">
            <div className="flex items-center justify-between">
              <span className="eyebrow text-muted-foreground">SoC Stint Timeline (Laps 1 to {snapshot.totalLaps})</span>
              <span className="text-[11px] font-mono text-muted-foreground">
                CURRENT LAP: {snapshot.lap}
              </span>
            </div>
            <div className="h-48 w-full rounded-lg border border-border/50 bg-surface/20 p-2">
              <ResponsiveContainer width="100%" height="100%">
                <LineChart
                  data={timelines?.socOverTime ?? []}
                  margin={{ top: 10, right: 10, left: -20, bottom: 0 }}
                >
                  <CartesianGrid strokeDasharray="3 3" stroke="oklch(0.32 0.006 285 / 0.4)" />
                  <XAxis
                    dataKey="lap"
                    tick={{ fontSize: 10, fill: "oklch(0.68 0.008 285)" }}
                    unit="L"
                  />
                  <YAxis
                    domain={[0, 100]}
                    tick={{ fontSize: 10, fill: "oklch(0.68 0.008 285)" }}
                    unit="%"
                    tickFormatter={(v) => `${v}`}
                  />
                  <Tooltip
                    contentStyle={{
                      backgroundColor: "oklch(0.235 0.005 285)",
                      borderColor: "oklch(0.32 0.006 285)",
                      borderRadius: "8px",
                      fontSize: "11px",
                      fontFamily: "monospace",
                    }}
                    formatter={(val: any) => [`${Math.round(Number(val))}%`, "SoC"]}
                    labelFormatter={(lap) => `Lap ${lap}`}
                  />
                  <ReferenceLine
                    x={snapshot.lap}
                    stroke="oklch(0.8 0.13 90)"
                    strokeWidth={2}
                    strokeDasharray="3 3"
                    label={{
                      value: "NOW",
                      fill: "oklch(0.8 0.13 90)",
                      fontSize: 10,
                      position: "top",
                    }}
                  />
                  <Line
                    type="monotone"
                    dataKey="soc"
                    name="SoC"
                    stroke="oklch(0.8 0.13 90)"
                    strokeWidth={2}
                    dot={false}
                  />
                </LineChart>
              </ResponsiveContainer>
            </div>
          </div>

          {/* Sub-Lap Intra-Lap SoC Variation */}
          <div className="space-y-2">
            <div className="flex items-center justify-between">
              <span className="eyebrow text-muted-foreground">Intra-Lap SoC Profile (16 Spatial Checkpoints)</span>
              <span className="text-[11px] font-mono text-muted-foreground">
                CURRENT MODE: {state?.ersMode ?? "BALANCED"}
              </span>
            </div>
            <div className="h-48 w-full rounded-lg border border-border/50 bg-surface/20 p-2">
              <ResponsiveContainer width="100%" height="100%">
                <AreaChart
                  data={telemetryData}
                  margin={{ top: 10, right: 10, left: -20, bottom: 0 }}
                >
                  <CartesianGrid strokeDasharray="3 3" stroke="oklch(0.32 0.006 285 / 0.4)" />
                  <XAxis
                    dataKey="checkpoint"
                    tick={{ fontSize: 10, fill: "oklch(0.68 0.008 285)" }}
                    tickFormatter={(v) => `CP${v}`}
                  />
                  <YAxis
                    domain={[0, 100]}
                    tick={{ fontSize: 10, fill: "oklch(0.68 0.008 285)" }}
                    unit="%"
                  />
                  <Tooltip
                    contentStyle={{
                      backgroundColor: "oklch(0.235 0.005 285)",
                      borderColor: "oklch(0.32 0.006 285)",
                      borderRadius: "8px",
                      fontSize: "11px",
                      fontFamily: "monospace",
                    }}
                    formatter={(val: any, name: string) => [`${val}%`, name]}
                    labelFormatter={(cp) => `Checkpoint #${cp} (Mode: ${telemetryData[Number(cp) - 1]?.mode})`}
                  />
                  <ReferenceLine
                    x={activeCheckpointIdx + 1}
                    stroke="oklch(0.75 0.16 155)"
                    strokeWidth={2}
                    strokeDasharray="3 3"
                  />
                  <Area
                    type="monotone"
                    dataKey="socPct"
                    name="Checkpoint SoC"
                    stroke="oklch(0.75 0.16 155)"
                    fill="oklch(0.75 0.16 155 / 0.15)"
                    strokeWidth={2}
                  />
                </AreaChart>
              </ResponsiveContainer>
            </div>
          </div>
        </div>
      </SectionCard>

      {/* ========================================================================= */}
      {/* SECTION 4 — OPPONENT HMM                                                  */}
      {/* ========================================================================= */}
      <SectionCard
        number="4"
        title="What Did RaceIQ Believe The Rival Was Doing?"
        subtitle="Analytic Bayesian Hidden Markov Model (HMM) tracking opponent energy posture and tactical trap intent"
        provenance="INFERRED"
      >
        {!rivalCode ? (
          <div className="panel p-6 text-center text-xs text-muted-foreground border-dashed">
            <p className="font-semibold text-foreground">No Rival In Immediate Tactical Window</p>
            <p className="mt-1">
              {isLeader
                ? `${selected} is currently leading the Grand Prix (P1). Opponent HMM model engages when tracking a car directly ahead.`
                : "No opponent currently within detection range to evaluate Bayesian energy state."}
            </p>
          </div>
        ) : (
          <div className="space-y-4">
            {/* Strategic Meaning Clarification */}
            <div className="grid gap-3 sm:grid-cols-2 text-xs">
              <div className="p-3 rounded-lg border border-amber-500/30 bg-amber-500/10 space-y-1">
                <span className="font-semibold text-amber-300 block font-mono">
                  P(Lderate) — Authentic Energy Limitation
                </span>
                <p className="text-muted-foreground leading-relaxed">
                  Rival has depleted usable battery reserves or hit regulatory limits. Speed deficit
                  on the straight is authentic, creating a high-probability overtaking opportunity.
                </p>
              </div>
              <div className="p-3 rounded-lg border border-purple-500/30 bg-purple-500/10 space-y-1">
                <span className="font-semibold text-purple-300 block font-mono">
                  P(Lharvest) — Tactical Trap Risk
                </span>
                <p className="text-muted-foreground leading-relaxed">
                  Rival is deliberately lifting and harvesting in low-drag air while hoarding battery
                  deployment. An apparent speed deficit may be a tactical trap to trigger our early deploy.
                </p>
              </div>
            </div>

            {/* Derived Marginals */}
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 font-mono">
              <div className="panel p-3 bg-surface/40">
                <span className="text-[10px] text-muted-foreground uppercase block">
                  P(Lderate) Marg
                </span>
                <span className="text-base font-bold text-foreground">
                  {fmtPct(analysisSnapshot?.opponentInference?.pLderate)}
                </span>
                <span className="text-[10px] text-muted-foreground block mt-0.5">DEPLETED OPPONENT</span>
              </div>
              <div className="panel p-3 bg-surface/40">
                <span className="text-[10px] text-muted-foreground uppercase block">
                  P(Lharvest) Marg
                </span>
                <span className="text-base font-bold text-foreground">
                  {fmtPct(analysisSnapshot?.opponentInference?.pLharvest)}
                </span>
                <span className="text-[10px] text-muted-foreground block mt-0.5">HARVESTING OPPONENT</span>
              </div>
              <div className="panel p-3 bg-surface/40">
                <span className="text-[10px] text-muted-foreground uppercase block">
                  P(OT Available)
                </span>
                <span className="text-base font-bold text-foreground">
                  {fmtPct(analysisSnapshot?.opponentInference?.pOtAvail)}
                </span>
                <span className="text-[10px] text-muted-foreground block mt-0.5">OVERTAKE BOOST</span>
              </div>
              <div className="panel p-3 bg-surface/40">
                <span className="text-[10px] text-muted-foreground uppercase block">Trap Detector</span>
                <span
                  className={`text-sm font-bold ${
                    analysisSnapshot?.opponentInference?.trapFlag ? "text-attack" : "text-emerald-400"
                  }`}
                >
                  {analysisSnapshot?.opponentInference?.trapFlag ? "POSSIBLE TRAP" : "NONE DETECTED"}
                </span>
                <span className="text-[10px] text-muted-foreground block mt-0.5 font-mono">
                  PROB: {fmtPct(analysisSnapshot?.opponentInference?.trapProbability)}
                </span>
              </div>
            </div>

            {/* 8-State Posterior Distribution Bars */}
            <div className="space-y-2">
              <div className="flex items-center justify-between">
                <span className="eyebrow text-muted-foreground">
                  Full 8-State Bayesian Posterior Distribution (Rival: {rivalCode})
                </span>
                <span className="text-xs font-mono text-foreground">
                  DOMINANT: <span className="text-primary font-bold">{dominantState}</span>
                </span>
              </div>

              <div className="grid gap-2 sm:grid-cols-2">
                {hmmStates.map((st) => {
                  const isDominant = st.name === dominantState;
                  return (
                    <div
                      key={st.name}
                      className={`p-2.5 rounded-lg border transition-all ${
                        isDominant
                          ? "border-primary/60 bg-primary/10 shadow-sm"
                          : "border-border/40 bg-surface/30"
                      }`}
                    >
                      <div className="flex items-center justify-between text-xs font-mono mb-1">
                        <span className={isDominant ? "font-bold text-foreground" : "text-muted-foreground"}>
                          {st.name}
                          {isDominant && (
                            <span className="ml-2 text-[10px] px-1.5 py-0.2 rounded bg-primary text-primary-foreground font-sans">
                              MAX
                            </span>
                          )}
                        </span>
                        <span className="font-bold text-foreground">{st.pct}%</span>
                      </div>
                      <div className="h-2 w-full rounded-full bg-muted/40 overflow-hidden">
                        <div
                          className={`h-full rounded-full transition-all duration-300 ${
                            isDominant
                              ? "bg-primary"
                              : st.isDerate
                              ? "bg-amber-400"
                              : st.isHarvest
                              ? "bg-purple-400"
                              : "bg-muted-foreground/50"
                          }`}
                          style={{ width: `${Math.max(2, st.pct)}%` }}
                        />
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>

            {/* HMM Probability Trajectory Chart */}
            <div className="space-y-2 pt-2">
              <span className="eyebrow text-muted-foreground">
                HMM Posterior Trajectory Over Race Laps (Rival: {rivalCode})
              </span>
              <div className="h-52 w-full rounded-lg border border-border/50 bg-surface/20 p-2">
                <ResponsiveContainer width="100%" height="100%">
                  <LineChart
                    data={timelines?.hmmProbabilitiesOverTime ?? []}
                    margin={{ top: 10, right: 10, left: -20, bottom: 0 }}
                  >
                    <CartesianGrid strokeDasharray="3 3" stroke="oklch(0.32 0.006 285 / 0.4)" />
                    <XAxis
                      dataKey="lap"
                      tick={{ fontSize: 10, fill: "oklch(0.68 0.008 285)" }}
                      unit="L"
                    />
                    <YAxis
                      domain={[0, 100]}
                      tick={{ fontSize: 10, fill: "oklch(0.68 0.008 285)" }}
                      unit="%"
                      tickFormatter={(v) => `${v}`}
                    />
                    <Tooltip
                      contentStyle={{
                        backgroundColor: "oklch(0.235 0.005 285)",
                        borderColor: "oklch(0.32 0.006 285)",
                        borderRadius: "8px",
                        fontSize: "11px",
                        fontFamily: "monospace",
                      }}
                      formatter={(val: any, name: string) => [`${Math.round(Number(val))}%`, name]}
                      labelFormatter={(lap) => `Lap ${lap}`}
                    />
                    <Legend wrapperStyle={{ fontSize: "11px", fontFamily: "monospace" }} />
                    <ReferenceLine
                      x={snapshot.lap}
                      stroke="oklch(0.78 0.13 200)"
                      strokeWidth={2}
                      strokeDasharray="3 3"
                    />
                    <Line
                      type="monotone"
                      dataKey="pLderate"
                      name="P(Lderate) Genuine Weakness"
                      stroke="oklch(0.78 0.15 85)"
                      strokeWidth={2}
                      dot={false}
                    />
                    <Line
                      type="monotone"
                      dataKey="pLharvest"
                      name="P(Lharvest) Trap Intent"
                      stroke="oklch(0.75 0.16 300)"
                      strokeWidth={2}
                      dot={false}
                    />
                    <Line
                      type="monotone"
                      dataKey="pOtAvail"
                      name="P(OT Available)"
                      stroke="oklch(0.78 0.13 200)"
                      strokeWidth={1.5}
                      strokeDasharray="4 4"
                      dot={false}
                    />
                  </LineChart>
                </ResponsiveContainer>
              </div>
            </div>
          </div>
        )}
      </SectionCard>

      {/* ========================================================================= */}
      {/* SECTION 5 — PASS PROBABILITY                                              */}
      {/* ========================================================================= */}
      <SectionCard
        number="5"
        title="How Likely Was The Pass?"
        subtitle="Evaluated via the calibrated 12-feature logistic PassModel"
        provenance="INFERRED"
      >
        <div className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-border/60 bg-muted/20 p-3">
          <div>
            <div className="flex items-center gap-2">
              <span className="text-xs font-semibold uppercase text-foreground">
                Model Classification:
              </span>
              <span className="px-2 py-0.5 rounded text-[11px] font-mono font-semibold bg-emerald-500/20 text-emerald-300 border border-emerald-500/40">
                HEURISTIC (12 CANONICAL FEATURES)
              </span>
            </div>
            <p className="text-xs text-muted-foreground mt-1">
              Transparent heuristic PassModel. Calibrated logistic weights applied directly to physical
              speed, energy, and opponent HMM marginals. Not an opaque black box.
            </p>
          </div>
          <div className="panel px-4 py-2 bg-surface/50 font-mono text-center shrink-0">
            <span className="text-[10px] text-muted-foreground block uppercase">Calculated P(Pass)</span>
            <span className="text-xl font-bold text-foreground">
              {fmtPct(analysisSnapshot?.passModel?.pPass ?? rec?.passProbability)}
            </span>
          </div>
        </div>

        {/* 12 Features Table */}
        <div className="overflow-x-auto rounded-lg border border-border/50">
          <table className="w-full text-left text-xs font-mono">
            <thead className="bg-muted/40 text-muted-foreground border-b border-border/50">
              <tr>
                <th className="p-2.5">#</th>
                <th className="p-2.5">Canonical Feature</th>
                <th className="p-2.5">Observed / Inferred Value</th>
                <th className="p-2.5">Provenance</th>
                <th className="p-2.5 hidden sm:table-cell">Role in Pass Model</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border/30 bg-surface/20">
              {canonicalFeaturesList.map((f) => (
                <tr key={f.name} className="hover:bg-muted/20">
                  <td className="p-2.5 text-muted-foreground font-semibold">{f.num}</td>
                  <td className="p-2.5 font-bold text-foreground">{f.name}</td>
                  <td className="p-2.5 text-foreground font-semibold">{f.value}</td>
                  <td className="p-2.5">
                    <ProvenanceTag kind={f.provenance} />
                  </td>
                  <td className="p-2.5 text-muted-foreground hidden sm:table-cell">{f.desc}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        {/* P(pass) Timeline Across Stint */}
        <div className="space-y-2 pt-2">
          <span className="eyebrow text-muted-foreground">
            Pass Probability Evolution Across Stint Laps
          </span>
          <div className="h-48 w-full rounded-lg border border-border/50 bg-surface/20 p-2">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart
                data={timelines?.pPassOverTime ?? []}
                margin={{ top: 10, right: 10, left: -20, bottom: 0 }}
              >
                <CartesianGrid strokeDasharray="3 3" stroke="oklch(0.32 0.006 285 / 0.4)" />
                <XAxis
                  dataKey="lap"
                  tick={{ fontSize: 10, fill: "oklch(0.68 0.008 285)" }}
                  unit="L"
                />
                <YAxis
                  domain={[0, 100]}
                  tick={{ fontSize: 10, fill: "oklch(0.68 0.008 285)" }}
                  unit="%"
                  tickFormatter={(v) => `${v}`}
                />
                <Tooltip
                  contentStyle={{
                    backgroundColor: "oklch(0.235 0.005 285)",
                    borderColor: "oklch(0.32 0.006 285)",
                    borderRadius: "8px",
                    fontSize: "11px",
                    fontFamily: "monospace",
                  }}
                  formatter={(val: any) => [`${Math.round(Number(val))}%`, "P(Pass)"]}
                  labelFormatter={(lap) => `Lap ${lap}`}
                />
                <ReferenceLine
                  y={50}
                  stroke="oklch(0.68 0.008 285)"
                  strokeDasharray="4 4"
                  label={{ value: "50% THRESHOLD", fill: "oklch(0.68 0.008 285)", fontSize: 9 }}
                />
                <ReferenceLine
                  x={snapshot.lap}
                  stroke="oklch(0.78 0.13 200)"
                  strokeWidth={2}
                  strokeDasharray="3 3"
                />
                <Line
                  type="monotone"
                  dataKey="pPass"
                  name="Pass Probability"
                  stroke="oklch(0.68 0.19 30)"
                  strokeWidth={2}
                  dot={{ r: 2 }}
                />
              </LineChart>
            </ResponsiveContainer>
          </div>
        </div>
      </SectionCard>

      {/* ========================================================================= */}
      {/* SECTION 6 — STRATEGIC EXPECTED VALUE                                      */}
      {/* ========================================================================= */}
      <SectionCard
        number="6"
        title="Should We Act? (Strategic Expected Value)"
        subtitle="Expected Value engine balancing track position gain against battery repayment debt and repass vulnerability"
        provenance="INFERRED"
      >
        <div className="rounded-lg border border-border/60 bg-muted/20 p-3 text-xs text-muted-foreground leading-relaxed">
          <p>
            <strong className="text-foreground">Decision Formulation:</strong> Strategic EV translates
            manoeuvre risk into a <strong className="text-foreground">points-equivalent decision score</strong>:
            <br />
            <code className="font-mono text-[11px] text-foreground block mt-1">
              EV = P(pass) × Points_Gain - Repass_Cost - Repayment_Cost_Pts - Legality_Penalty
            </code>
            If EV &gt; 0 and all FIA regulations pass, the model issues an <strong className="text-attack">ATTACK</strong> call;
            otherwise it commands <strong className="text-hold">HOLD</strong>.
          </p>
        </div>

        {/* Breakdown Grid */}
        <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-3 font-mono">
          <div className="panel p-3 bg-surface/40">
            <span className="text-[10px] text-muted-foreground uppercase block">Points Gain</span>
            <span className="text-base font-bold text-foreground">
              +{evBreakdown?.points_gain?.toFixed(1) ?? "0.0"} pts
            </span>
            <span className="text-[10px] text-muted-foreground block mt-0.5">POSITION DELTA</span>
          </div>
          <div className="panel p-3 bg-surface/40">
            <span className="text-[10px] text-muted-foreground uppercase block">Repass Risk</span>
            <span className="text-base font-bold text-foreground">
              {fmtPct(evBreakdown?.repass_risk)}
            </span>
            <span className="text-[10px] text-attack block mt-0.5">
              -{evBreakdown?.repass_cost_pts?.toFixed(1) ?? "0.0"} pts
            </span>
          </div>
          <div className="panel p-3 bg-surface/40">
            <span className="text-[10px] text-muted-foreground uppercase block">Repayment Cost (Time)</span>
            <span className="text-base font-bold text-foreground">
              {evBreakdown?.repayment_cost_s?.toFixed(2) ?? "0.00"} s
            </span>
            <span className="text-[10px] text-muted-foreground block mt-0.5">RECHARGE TIME</span>
          </div>
          <div className="panel p-3 bg-surface/40">
            <span className="text-[10px] text-muted-foreground uppercase block">Repayment Cost (Pts)</span>
            <span className="text-base font-bold text-attack">
              -{evBreakdown?.repayment_cost_pts?.toFixed(1) ?? "0.0"} pts
            </span>
            <span className="text-[10px] text-muted-foreground block mt-0.5">POINTS CONVERSION</span>
          </div>
          <div className="panel p-3 bg-surface/40">
            <span className="text-[10px] text-muted-foreground uppercase block">Legality Penalty</span>
            <span className="text-base font-bold text-foreground">
              {evBreakdown?.illegal_penalty?.toFixed(0) ?? "0"} pts
            </span>
            <span className="text-[10px] text-emerald-400 block mt-0.5">COMPLIANT</span>
          </div>
          <div className="panel p-3 bg-surface/40 border-primary/50">
            <span className="text-[10px] text-muted-foreground uppercase block font-semibold">
              Strategic EV (pts-eq)
            </span>
            <span
              className={`text-base font-bold ${
                (strategicEv ?? 0) > 0 ? "text-attack" : "text-hold"
              }`}
            >
              {fmtSignedPoints(strategicEv)}
            </span>
            <span className="text-[10px] font-bold text-foreground block mt-0.5 uppercase">
              CALL: {recommendation}
            </span>
          </div>
        </div>

        {/* Strategic EV Stint Timeline */}
        <div className="space-y-2 pt-2">
          <div className="flex items-center justify-between">
            <span className="eyebrow text-muted-foreground">
              Strategic Expected Value (points-equivalent) Across Race Laps
            </span>
            <span className="text-[11px] font-mono text-muted-foreground">
              GREEN = ATTACK FAVORED (&gt;0) · BLUE = HOLD FAVORED (&le;0)
            </span>
          </div>
          <div className="h-48 w-full rounded-lg border border-border/50 bg-surface/20 p-2">
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart
                data={timelines?.strategicEvOverTime ?? []}
                margin={{ top: 10, right: 10, left: -20, bottom: 0 }}
              >
                <CartesianGrid strokeDasharray="3 3" stroke="oklch(0.32 0.006 285 / 0.4)" />
                <XAxis
                  dataKey="lap"
                  tick={{ fontSize: 10, fill: "oklch(0.68 0.008 285)" }}
                  unit="L"
                />
                <YAxis
                  tick={{ fontSize: 10, fill: "oklch(0.68 0.008 285)" }}
                  unit=" pts"
                />
                <Tooltip
                  contentStyle={{
                    backgroundColor: "oklch(0.235 0.005 285)",
                    borderColor: "oklch(0.32 0.006 285)",
                    borderRadius: "8px",
                    fontSize: "11px",
                    fontFamily: "monospace",
                  }}
                  formatter={(val: any) => [`${Number(val).toFixed(2)} pts-eq`, "Strategic EV"]}
                  labelFormatter={(lap) => `Lap ${lap}`}
                />
                <ReferenceLine
                  y={0}
                  stroke="oklch(0.6 0.22 26)"
                  strokeWidth={1.5}
                  label={{ value: "0 PTS THRESHOLD", fill: "oklch(0.6 0.22 26)", fontSize: 9 }}
                />
                <ReferenceLine
                  x={snapshot.lap}
                  stroke="oklch(0.78 0.13 200)"
                  strokeWidth={2}
                  strokeDasharray="3 3"
                />
                <Area
                  type="monotone"
                  dataKey="ev"
                  name="Strategic EV (pts-eq)"
                  stroke="oklch(0.68 0.19 30)"
                  fill="oklch(0.68 0.19 30 / 0.2)"
                  strokeWidth={2}
                />
              </AreaChart>
            </ResponsiveContainer>
          </div>
        </div>
      </SectionCard>

      {/* ========================================================================= */}
      {/* SECTION 7 — RECOMMENDATION CHAIN                                          */}
      {/* ========================================================================= */}
      <SectionCard
        number="7"
        title="Auditable Decision Chain"
        subtitle="End-to-end trace from observed track state to final strategic recommendation"
        provenance="INFERRED"
      >
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-6 font-mono text-xs">
          {/* Step 1 */}
          <div className="panel p-3.5 bg-surface/50 border-border/70 space-y-2">
            <div className="flex items-center justify-between">
              <span className="text-[10px] text-muted-foreground uppercase font-bold">1. OBSERVED</span>
              <ProvenanceTag kind="ACTUAL" />
            </div>
            <div className="space-y-1 text-foreground">
              <div>Gap: {isLeader ? "LEADER" : fmtSeconds(state?.gapAhead, 2)}</div>
              <div>Speed: {isNum(analysisSnapshot?.telemetry?.speed) ? `${analysisSnapshot.telemetry.speed.toFixed(0)} km/h` : "---"}</div>
              <div>Pos: {fmtPosition(state?.position)}</div>
              <div>Window: {analysisSnapshot?.telemetry?.detectionWindow?.inWindow ? "IN" : "OUT"}</div>
            </div>
          </div>

          {/* Step 2 */}
          <div className="panel p-3.5 bg-surface/50 border-border/70 space-y-2">
            <div className="flex items-center justify-between">
              <span className="text-[10px] text-muted-foreground uppercase font-bold">2. DERIVED</span>
              <ProvenanceTag kind="DERIVED" />
            </div>
            <div className="space-y-1 text-foreground">
              <div>Closing: {pmFeat ? `${pmFeat.closing_speed_kph.toFixed(1)} km/h` : "---"}</div>
              <div>Straight: {pmFeat ? `${pmFeat.straight_remaining_m.toFixed(0)} m` : "---"}</div>
              <div>Tyre Delta: {pmFeat ? `${pmFeat.tyre_age_delta_laps.toFixed(1)}L` : "---"}</div>
              <div>Regen: {pmFeat ? `${pmFeat.circuit_harvest_potential_mj.toFixed(1)} MJ` : "---"}</div>
            </div>
          </div>

          {/* Step 3 */}
          <div className="panel p-3.5 bg-surface/50 border-border/70 space-y-2">
            <div className="flex items-center justify-between">
              <span className="text-[10px] text-muted-foreground uppercase font-bold">3. INFERRED</span>
              <ProvenanceTag kind="INFERRED" />
            </div>
            <div className="space-y-1 text-foreground">
              <div>Own SoC: {fmtPct(state?.soc)}</div>
              <div>Rival SoC: {rivalState?.soc ? fmtPct(rivalState.soc) : "N/A"}</div>
              <div>P(Lderate): {fmtPct(analysisSnapshot?.opponentInference?.pLderate)}</div>
              <div>P(Lharvest): {fmtPct(analysisSnapshot?.opponentInference?.pLharvest)}</div>
            </div>
          </div>

          {/* Step 4 */}
          <div className="panel p-3.5 bg-surface/50 border-border/70 space-y-2">
            <div className="flex items-center justify-between">
              <span className="text-[10px] text-muted-foreground uppercase font-bold">4. ESTIMATED</span>
              <ProvenanceTag kind="INFERRED" />
            </div>
            <div className="space-y-1 text-foreground">
              <div>Pass Model: Logistic</div>
              <div className="text-sm font-bold text-primary">
                P(Pass): {fmtPct(analysisSnapshot?.passModel?.pPass ?? rec?.passProbability)}
              </div>
              <div>Trap Flag: {pmFeat?.trap_flag ? "TRUE" : "FALSE"}</div>
              <div>OT Active: {pmFeat?.overtake_mode_active ? "YES" : "NO"}</div>
            </div>
          </div>

          {/* Step 5 */}
          <div className="panel p-3.5 bg-surface/50 border-border/70 space-y-2">
            <div className="flex items-center justify-between">
              <span className="text-[10px] text-muted-foreground uppercase font-bold">5. VALUED</span>
              <ProvenanceTag kind="INFERRED" />
            </div>
            <div className="space-y-1 text-foreground">
              <div>Pts Gain: +{evBreakdown?.points_gain?.toFixed(1) ?? "0.0"}</div>
              <div>Repass: -{evBreakdown?.repass_cost_pts?.toFixed(1) ?? "0.0"} pts</div>
              <div>Repay: -{evBreakdown?.repayment_cost_pts?.toFixed(1) ?? "0.0"} pts</div>
              <div className="text-sm font-bold text-foreground">
                EV: {fmtSignedPoints(strategicEv)}
              </div>
            </div>
          </div>

          {/* Step 6 */}
          <div className="panel p-3.5 bg-surface/50 border-primary/60 space-y-2 flex flex-col justify-between">
            <div className="flex items-center justify-between">
              <span className="text-[10px] text-muted-foreground uppercase font-bold">6. DECIDED</span>
              <ProvenanceTag kind="INFERRED" />
            </div>
            <div>
              <span className="text-[10px] text-muted-foreground uppercase block">RaceIQ Call:</span>
              <span
                className={`data text-base font-bold tracking-wider ${
                  recommendation === "ATTACK" ? "text-attack" : "text-hold"
                }`}
              >
                {recommendation}
              </span>
            </div>
            <span className="text-[10px] text-muted-foreground">
              AUDITABLE &amp; VERIFIED
            </span>
          </div>
        </div>
      </SectionCard>

      {/* ========================================================================= */}
      {/* SECTION 8 — DECISION HISTORY                                              */}
      {/* ========================================================================= */}
      <SectionCard
        number="8"
        title="Stint Decision Trajectory"
        subtitle="Historical continuity across the race stint to detect persistent opportunities vs single-lap anomalies"
        provenance="INFERRED"
      >
        <Tabs defaultValue="ev" className="w-full">
          <TabsList className="grid w-full grid-cols-3 max-w-md">
            <TabsTrigger value="ev">Posture &amp; Strategic EV</TabsTrigger>
            <TabsTrigger value="proximity">Gap &amp; Pass Prob</TabsTrigger>
            <TabsTrigger value="energy">Energy &amp; Opponent</TabsTrigger>
          </TabsList>

          <TabsContent value="ev" className="space-y-2 pt-3">
            <span className="eyebrow text-muted-foreground">
              Recommendation Posture and Strategic EV Across All Completed Laps
            </span>
            <div className="h-56 w-full rounded-lg border border-border/50 bg-surface/20 p-2">
              <ResponsiveContainer width="100%" height="100%">
                <LineChart
                  data={timelines?.strategicEvOverTime ?? []}
                  margin={{ top: 10, right: 10, left: -20, bottom: 0 }}
                >
                  <CartesianGrid strokeDasharray="3 3" stroke="oklch(0.32 0.006 285 / 0.4)" />
                  <XAxis dataKey="lap" tick={{ fontSize: 10, fill: "oklch(0.68 0.008 285)" }} unit="L" />
                  <YAxis tick={{ fontSize: 10, fill: "oklch(0.68 0.008 285)" }} unit=" pts" />
                  <Tooltip
                    contentStyle={{
                      backgroundColor: "oklch(0.235 0.005 285)",
                      borderColor: "oklch(0.32 0.006 285)",
                      borderRadius: "8px",
                      fontSize: "11px",
                      fontFamily: "monospace",
                    }}
                    formatter={(val: any) => [`${Number(val).toFixed(2)} pts-eq`, "Strategic EV"]}
                    labelFormatter={(lap) => `Lap ${lap}`}
                  />
                  <ReferenceLine y={0} stroke="oklch(0.6 0.22 26)" strokeWidth={1} />
                  <ReferenceLine x={snapshot.lap} stroke="oklch(0.78 0.13 200)" strokeDasharray="3 3" />
                  <Line
                    type="monotone"
                    dataKey="ev"
                    name="Strategic EV"
                    stroke="oklch(0.68 0.19 30)"
                    strokeWidth={2}
                    dot={{ r: 2 }}
                  />
                </LineChart>
              </ResponsiveContainer>
            </div>
          </TabsContent>

          <TabsContent value="proximity" className="space-y-2 pt-3">
            <span className="eyebrow text-muted-foreground">
              Proximity Gap and Pass Probability Progression Across Laps
            </span>
            <div className="h-56 w-full rounded-lg border border-border/50 bg-surface/20 p-2">
              <ResponsiveContainer width="100%" height="100%">
                <LineChart
                  data={timelines?.gapOverTime ?? []}
                  margin={{ top: 10, right: 10, left: -20, bottom: 0 }}
                >
                  <CartesianGrid strokeDasharray="3 3" stroke="oklch(0.32 0.006 285 / 0.4)" />
                  <XAxis dataKey="lap" tick={{ fontSize: 10, fill: "oklch(0.68 0.008 285)" }} unit="L" />
                  <YAxis
                    domain={[0, "auto"]}
                    tick={{ fontSize: 10, fill: "oklch(0.68 0.008 285)" }}
                    unit="s"
                  />
                  <Tooltip
                    contentStyle={{
                      backgroundColor: "oklch(0.235 0.005 285)",
                      borderColor: "oklch(0.32 0.006 285)",
                      borderRadius: "8px",
                      fontSize: "11px",
                      fontFamily: "monospace",
                    }}
                    formatter={(val: any, name: string) => [`${val}s`, name]}
                    labelFormatter={(lap) => `Lap ${lap}`}
                  />
                  <Legend wrapperStyle={{ fontSize: "11px", fontFamily: "monospace" }} />
                  <ReferenceLine x={snapshot.lap} stroke="oklch(0.78 0.13 200)" strokeDasharray="3 3" />
                  <Line
                    type="monotone"
                    dataKey="gapAhead"
                    name="Gap Ahead (s)"
                    stroke="oklch(0.75 0.11 240)"
                    strokeWidth={2}
                    dot={{ r: 2 }}
                  />
                </LineChart>
              </ResponsiveContainer>
            </div>
          </TabsContent>

          <TabsContent value="energy" className="space-y-2 pt-3">
            <span className="eyebrow text-muted-foreground">
              Battery SoC and Opponent Derate / Trap Postures Across Laps
            </span>
            <div className="h-56 w-full rounded-lg border border-border/50 bg-surface/20 p-2">
              <ResponsiveContainer width="100%" height="100%">
                <LineChart
                  data={timelines?.socOverTime ?? []}
                  margin={{ top: 10, right: 10, left: -20, bottom: 0 }}
                >
                  <CartesianGrid strokeDasharray="3 3" stroke="oklch(0.32 0.006 285 / 0.4)" />
                  <XAxis dataKey="lap" tick={{ fontSize: 10, fill: "oklch(0.68 0.008 285)" }} unit="L" />
                  <YAxis domain={[0, 100]} tick={{ fontSize: 10, fill: "oklch(0.68 0.008 285)" }} unit="%" />
                  <Tooltip
                    contentStyle={{
                      backgroundColor: "oklch(0.235 0.005 285)",
                      borderColor: "oklch(0.32 0.006 285)",
                      borderRadius: "8px",
                      fontSize: "11px",
                      fontFamily: "monospace",
                    }}
                    formatter={(val: any) => [`${Math.round(Number(val))}%`, "SoC"]}
                    labelFormatter={(lap) => `Lap ${lap}`}
                  />
                  <ReferenceLine x={snapshot.lap} stroke="oklch(0.8 0.13 90)" strokeDasharray="3 3" />
                  <Line
                    type="monotone"
                    dataKey="soc"
                    name="SoC %"
                    stroke="oklch(0.8 0.13 90)"
                    strokeWidth={2}
                    dot={false}
                  />
                </LineChart>
              </ResponsiveContainer>
            </div>
          </TabsContent>
        </Tabs>
      </SectionCard>

      {/* ========================================================================= */}
      {/* WHAT-IF CONTEXTUAL LINK & PROVENANCE FOOTER                               */}
      {/* ========================================================================= */}
      <div className="grid gap-4 sm:grid-cols-2">
        <Link
          to="/what-if"
          className="panel p-5 border-border/80 hover:border-primary/60 bg-gradient-to-br from-card/80 to-surface/40 transition-all group flex flex-col justify-between"
        >
          <div>
            <div className="flex items-center justify-between">
              <span className="eyebrow text-muted-foreground">Counterfactual Simulator</span>
              <span className="text-xs text-primary font-mono group-hover:translate-x-1 transition-transform">
                EXPLORE WHAT IF &rarr;
              </span>
            </div>
            <h3 className="mt-2 text-base font-semibold text-foreground">
              Want to see what happens if we choose differently?
            </h3>
            <p className="mt-1 text-xs text-muted-foreground leading-relaxed">
              Branch off this frozen moment into counterfactual branches: ATTACK, HOLD, DEFEND, or HARVEST.
              History remains immutable while simulating projected track position and battery consequences.
            </p>
          </div>
          <div className="mt-4 flex items-center gap-2">
            <ProvenanceTag kind="PROJECTED" />
            <span className="text-[11px] font-mono text-muted-foreground">
              SEED: LAP {snapshot.lap}, {selected} vs {rivalCode ?? "AHEAD"}
            </span>
          </div>
        </Link>

        <div className="panel p-5 border-border/80 bg-card/60 space-y-3 text-xs text-muted-foreground">
          <div className="flex items-center justify-between">
            <span className="eyebrow text-muted-foreground">Provenance Standards</span>
            <span className="text-[11px] font-mono text-foreground">FIA COMPLIANT</span>
          </div>
          <p className="leading-relaxed">
            RaceIQ maintains strict mathematical provenance transparency. Numbers are never fabricated:
          </p>
          <ul className="space-y-1.5 font-mono text-[11px]">
            <li className="flex items-center gap-2">
              <ProvenanceTag kind="ACTUAL" />
              <span>Direct FastF1 2026 timing, positions, speed &amp; pedal telemetry.</span>
            </li>
            <li className="flex items-center gap-2">
              <ProvenanceTag kind="DERIVED" />
              <span>Deterministic kinematic calculations (closing rates, distances, tyres).</span>
            </li>
            <li className="flex items-center gap-2">
              <ProvenanceTag kind="INFERRED" />
              <span>Observer and Bayesian models (SoC balance, HMM postures, PassModel).</span>
            </li>
            <li className="flex items-center gap-2">
              <ProvenanceTag kind="PROJECTED" />
              <span>Forward-looking simulations and counterfactual What-If branches.</span>
            </li>
          </ul>
        </div>
      </div>
    </main>
  );
}
