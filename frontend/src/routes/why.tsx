import { createFileRoute, Link } from "@tanstack/react-router";
import { POSTURE_STYLE } from "@/components/raceiq/MatchupCard";
import { ProvenanceTag } from "@/components/raceiq/ProvenanceTag";
import type { Posture } from "@/lib/raceiq/contracts";
import { EMPTY, fmtClock, fmtGap, fmtPct } from "@/lib/raceiq/format";
import { useRaceIQ } from "@/lib/raceiq/store";

export const Route = createFileRoute("/why")({
  head: () => ({
    meta: [
      { title: "Why — RaceIQ" },
      {
        name: "description",
        content:
          "Why did RaceIQ make this decision? Race situation, model assessment, one pass probability and the reasons behind the call.",
      },
      { property: "og:title", content: "Why — RaceIQ" },
      {
        property: "og:description",
        content: "A judge-facing explanation of the RaceIQ decision at this replay state.",
      },
    ],
  }),
  component: Why,
});

interface SituationCardProps {
  label: string;
  code: string;
  team: string;
  position: number | undefined;
  gap: string;
  tyre: string;
  dominant?: boolean;
}

function SituationCard({
  label,
  code,
  team,
  position,
  gap,
  tyre,
  dominant = false,
}: SituationCardProps) {
  return (
    <div
      className={`rounded border p-3 ${
        dominant ? "border-primary/70 bg-primary/10" : "border-border bg-surface-raised"
      }`}
    >
      <p className="text-[10px] uppercase tracking-widest text-muted-foreground">{label}</p>
      <div className="mt-1.5 flex items-baseline gap-2">
        <span className={`text-xl font-bold ${dominant ? "text-primary" : "text-foreground"}`}>{code}</span>
        <span className="truncate text-xs text-muted-foreground">{team}</span>
      </div>
      <p className="mt-1 text-[11px] tabular-nums text-muted-foreground">
        {typeof position === "number" ? `P${position}` : EMPTY}
        {gap !== EMPTY ? ` · ${gap}` : ""}
        {tyre !== EMPTY ? ` · ${tyre}` : ""}
      </p>
    </div>
  );
}

function tyreShort(
  d: { tyre?: { compound?: string | null; ageLaps?: number | null } | null | undefined } | undefined,
): string {
  if (!d?.tyre?.compound) return EMPTY;
  const c = d.tyre.compound.toUpperCase();
  const letter =
    ({ SOFT: "S", MEDIUM: "M", HARD: "H", INTERMEDIATE: "I", WET: "W" } as Record<string, string>)[c] ??
    c.charAt(0);
  const age =
    typeof d.tyre.ageLaps === "number" ? `${Math.round(d.tyre.ageLaps)}L` : "";
  return age ? `${letter} ${age}` : letter;
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
    aheadOf,
    behindOf,
  } = useRaceIQ();

  const state = stateOf(selected);
  const driver = driverOf(selected);
  const rec = recommendationFor(selected);
  const analysis = analysisSnapshot;
  const ahead = aheadOf(selected);
  const behind = behindOf(selected);
  const aheadDriver = ahead ? driverOf(ahead.code) : null;
  const behindDriver = behind ? driverOf(behind.code) : null;

  const posture: Posture = analysis?.overtakeEv?.recommendation ?? rec?.posture ?? "HOLD";
  const pPass = analysis?.passModel?.pPass ?? rec?.passProbability;
  const energy = analysis?.energy;
  const soc = energy?.soc ?? state?.soc;
  const opp = analysis?.opponentInference;
  const rivalCode = opp?.rivalCode ?? ahead?.code ?? null;

  const opponentSummary = !rivalCode
    ? "No car directly ahead — the opponent model is not engaged."
    : opp?.trapFlag
      ? `${rivalCode} is conserving aggressively; RaceIQ treats the next overtake window as risky.`
      : `${rivalCode} is being tracked ahead. No trap signal: the opponent is racing normally.`;

  // 2-3 plain-language reasons, derived from internal model state. Raw model
  // probabilities stay internal to the engine and are never shown here.
  const reasons: string[] = [];
  if (state && state.position > 1 && ahead && typeof state.gapAhead === "number") {
    reasons.push(
      state.gapAhead <= 1.0
        ? `Gap to ${ahead.code} is inside the overtake window.`
        : `Gap to ${ahead.code} is outside the overtake window.`,
    );
  }
  if (typeof soc === "number") {
    reasons.push(
      soc >= 0.45
        ? "Estimated battery is sufficient to support the move."
        : "Estimated battery is low — RaceIQ is prioritising recovery.",
    );
  }
  if (energy?.ersMode === "CLIPPING") {
    reasons.push("Power delivery is clipped on this lap — an overtake would not carry.");
  } else if (energy?.ersMode) {
    reasons.push("Power delivery is healthy — no clipping on the approach.");
  }
  if (opp) {
    reasons.push(
      opp.trapFlag
        ? "The opponent is conserving aggressively — a trap signal."
        : "No trap signal from the opponent.",
    );
  }
  if (typeof pPass === "number") {
    reasons.push(
      pPass >= 0.6
        ? "The estimated pass probability supports an attempt."
        : pPass >= 0.35
          ? "The estimated pass probability is marginal."
          : "The estimated pass probability is too low to justify spending energy.",
    );
  }
  if (
    posture === "DEFEND" &&
    state &&
    typeof state.gapToLeader === "number" &&
    behind &&
    typeof behind.gapToLeader === "number"
  ) {
    const gapBehind = Math.max(0, behind.gapToLeader - state.gapToLeader);
    if (gapBehind < 1.2) {
      reasons.unshift(
        `Car behind (${behind.code}) is within ${fmtGap(gapBehind)} — hold the racing line.`,
      );
    }
  }
  const shownReasons = reasons.slice(0, 3);

  const gapAheadText =
    state?.position === 1 ? "LEADER" : ahead ? fmtGap(state?.gapAhead, 2) : EMPTY;
  const gapBehindText =
    behind && state && typeof behind.gapToLeader === "number" && typeof state.gapToLeader === "number"
      ? fmtGap(Math.max(0, behind.gapToLeader - state.gapToLeader), 2)
      : EMPTY;
  const pipeline = [
    "Observed race data",
    "Energy estimation",
    "Opponent inference",
    "Pass probability",
    "Strategic value",
    `DECISION — ${posture}`,
  ];

  return (
    <main className="mx-auto max-w-[1100px] px-4 py-6 sm:px-6 space-y-6">
      <header className="panel border border-border/80 p-5 sm:p-6">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <p className="eyebrow tracking-wider text-muted-foreground font-semibold">
            WHY · RACEIQ DECISION EXPLAINED
          </p>
          <div className="flex flex-wrap items-center gap-2">
            <ProvenanceTag kind={snapshot.positionsProvenance} />
            <ProvenanceTag kind="INFERRED" />
            <span className="text-[11px] text-muted-foreground font-mono">
              {circuit.event} · LAP {snapshot.lap}/{snapshot.totalLaps} · {fmtClock(snapshot.time)}
            </span>
          </div>
        </div>
        <h1 className="mt-4 text-xl sm:text-2xl font-bold tracking-tight text-foreground">
          WHY DID RACEIQ SAY <span className={POSTURE_STYLE[posture]}>{posture}</span>?
        </h1>
        <p className="mt-1 text-sm text-muted-foreground">
          The decision for <b className="text-foreground">{selected}</b> at this replay state, in
          plain language.
        </p>
        <div className="mt-3 flex flex-wrap gap-2">
          <Link
            to="/"
            className="data rounded border border-border px-2.5 py-1 text-xs text-muted-foreground transition-colors hover:bg-accent"
          >
            ← Live
          </Link>
          <Link
            to="/what-if"
            className="data rounded border border-primary/50 bg-primary/10 px-2.5 py-1 text-xs text-primary transition-colors hover:bg-primary/20"
          >
            What if?
          </Link>
        </div>
      </header>
      {/* 1 — RACE SITUATION */}
      <section className="panel p-4">
        <div className="flex items-center justify-between gap-2">
          <p className="eyebrow">1 · Race situation</p>
          <ProvenanceTag kind={snapshot.positionsProvenance} />
        </div>
        <div className="mt-3 grid gap-3 sm:grid-cols-[minmax(0,1fr)_minmax(0,1fr)_minmax(0,1fr)]">
          <SituationCard
            label="Ahead"
            code={ahead?.code ?? "—"}
            team={aheadDriver?.team ?? (ahead?.code ? "" : "leader / no car")}
            position={ahead?.position}
            gap={gapAheadText}
            tyre={tyreShort(ahead)}
          />
          <SituationCard
            label="Selected"
            code={selected}
            team={driver.team ?? "—"}
            position={state?.position}
            gap={gapAheadText}
            tyre={tyreShort(state)}
            dominant
          />
          <SituationCard
            label="Behind"
            code={behind?.code ?? "—"}
            team={behindDriver?.team ?? (behind?.code ? "" : "last place / no car")}
            position={behind?.position}
            gap={gapBehindText}
            tyre={tyreShort(behind)}
          />
        </div>
      </section>

      {/* 2 — MODEL ASSESSMENT */}
      <section className="panel p-4">
        <div className="flex items-center justify-between gap-2">
          <p className="eyebrow">2 · Model assessment</p>
          <ProvenanceTag kind="INFERRED" />
        </div>
        <dl className="mt-3 grid grid-cols-2 gap-3 sm:grid-cols-4">
          <div>
            <dt className="text-[11px] text-muted-foreground">Estimated SoC</dt>
            <dd className="data text-sm font-medium">{fmtPct(soc)}</dd>
          </div>
          <div>
            <dt className="text-[11px] text-muted-foreground">ERS state</dt>
            <dd className="data text-sm font-medium">{energy?.ersMode ?? EMPTY}</dd>
          </div>
          <div>
            <dt className="text-[11px] text-muted-foreground">Clipping</dt>
            <dd className="data text-sm font-medium">
              {typeof energy?.isClipping === "boolean"
                ? energy.isClipping
                  ? "YES"
                  : "NO"
                : EMPTY}
            </dd>
          </div>
          <div>
            <dt className="text-[11px] text-muted-foreground">Overtake window</dt>
            <dd className="data text-sm font-medium">
              {typeof state?.inDetectionWindow === "boolean"
                ? state.inDetectionWindow
                  ? "INSIDE"
                  : "OUTSIDE"
                : EMPTY}
            </dd>
          </div>
        </dl>
        <div className="mt-3 flex items-start gap-1.5 border-t border-border pt-2 text-xs text-muted-foreground">
          <span className="text-[10px] uppercase tracking-widest text-muted-foreground shrink-0">
            Opponent
          </span>
          <span className="min-w-0">{opponentSummary}</span>
        </div>
      </section>

      {/* 3 — ONE PASS PROBABILITY */}
      <section className="panel p-4">
        <div className="flex items-center justify-between gap-2">
          <p className="eyebrow">3 · Estimated pass probability</p>
          <ProvenanceTag kind="INFERRED" />
        </div>
        <p className="mt-3 text-3xl font-bold tabular-nums text-foreground">{fmtPct(pPass)}</p>
        <p className="text-[11px] text-muted-foreground">
          A single estimate from the RaceIQ heuristic model. RaceIQ does not claim a trained ML pass
          model; this value is a projection, not a guarantee.
        </p>
      </section>

      {/* 4 — DECISION */}
      <section className="panel p-4">
        <div className="flex items-center justify-between gap-2">
          <p className="eyebrow">4 · RaceIQ decision</p>
          <ProvenanceTag kind="INFERRED" />
        </div>
        <div className="mt-3 flex flex-wrap items-center gap-2">
          <span
            className={`data inline-flex items-center gap-2 rounded border px-3 py-1.5 text-base font-bold tracking-[0.12em] ${POSTURE_STYLE[posture]}`}
          >
            <span className="h-2 w-2 rounded-full bg-current" />
            {posture}
          </span>
          {rec?.headline && <span className="text-sm text-muted-foreground">{rec.headline}</span>}
        </div>
      </section>

      {/* 5 — REASONS */}
      <section className="panel p-4">
        <div className="flex items-center justify-between gap-2">
          <p className="eyebrow">5 · Why</p>
          <ProvenanceTag kind="INFERRED" />
        </div>
        {shownReasons.length > 0 ? (
          <ul className="mt-3 flex flex-col gap-2 text-sm text-foreground">
            {shownReasons.map((r) => (
              <li key={r} className="flex items-start gap-2">
                <span className="text-primary">•</span>
                <span className="min-w-0">{r}</span>
              </li>
            ))}
          </ul>
        ) : (
          <p className="mt-3 text-sm text-muted-foreground">No reasons available for this state.</p>
        )}
      </section>

      {/* 6 — PIPELINE */}
      <section className="panel p-4">
        <p className="eyebrow">6 · How the decision is built</p>
        <ol className="mt-3 flex flex-col gap-1.5 text-sm text-foreground">
          {pipeline.map((step, i) => (
            <li key={step} className="flex items-center gap-3">
              <span className="grid h-5 w-5 shrink-0 place-items-center rounded-md border border-border bg-surface text-[10px] font-semibold text-muted-foreground">
                {i + 1}
              </span>
              <span className={i === 5 ? POSTURE_STYLE[posture] : "text-foreground"}>{step}</span>
              {i < pipeline.length - 1 && <span className="text-border">↓</span>}
            </li>
          ))}
        </ol>
      </section>
    </main>
  );
}
