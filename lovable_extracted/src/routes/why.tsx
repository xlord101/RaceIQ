import { createFileRoute } from "@tanstack/react-router";
import { POSTURE_STYLE } from "@/components/raceiq/MatchupCard";
import { ProvenanceTag } from "@/components/raceiq/ProvenanceTag";
import type { Provenance } from "@/lib/raceiq/contracts";
import {
  EMPTY,
  fmtPct,
  fmtPoints,
  fmtSeconds,
  fmtSignedSeconds,
  isNum,
} from "@/lib/raceiq/format";
import { useRaceIQ } from "@/lib/raceiq/store";

export const Route = createFileRoute("/why")({
  head: () => ({
    meta: [
      { title: "Why — RaceIQ analysis" },
      {
        name: "description",
        content:
          "Open up a RaceIQ call layer by layer: energy estimate, opponent state, pass probability and the constraints behind it.",
      },
      { property: "og:title", content: "Why — RaceIQ analysis" },
      {
        property: "og:description",
        content: "Progressive disclosure of the RaceIQ decision chain for the selected driver.",
      },
    ],
  }),
  component: Why,
});

function Section({
  title,
  summary,
  provenance,
  children,
  open,
}: {
  title: string;
  summary: string;
  provenance: Provenance;
  children: React.ReactNode;
  open?: boolean;
}) {
  return (
    <details open={open} className="panel group px-4 py-3">
      <summary className="grid cursor-pointer grid-cols-[minmax(0,1fr)_auto] items-center gap-3">
        <span className="min-w-0">
          <span className="block text-sm font-medium">{title}</span>
          <span className="block truncate text-xs text-muted-foreground">{summary}</span>
        </span>
        <span className="flex shrink-0 items-center gap-2">
          <ProvenanceTag kind={provenance} />
          <span className="data text-xs text-muted-foreground group-open:hidden">+</span>
          <span className="data hidden text-xs text-muted-foreground group-open:inline">−</span>
        </span>
      </summary>
      <div className="mt-3 space-y-2 border-t border-border pt-3 text-xs text-muted-foreground">
        {children}
      </div>
    </details>
  );
}

function Why() {
  const { snapshot, selected, circuit, driver: driverOf, stateOf, recommendationFor } = useRaceIQ();
  const state = stateOf(selected);
  const driver = driverOf(selected);
  const rec = recommendationFor(selected);
  const ahead = snapshot.drivers.find((d) => d.position === (state?.position ?? 0) - 1);
  const energyProv = snapshot.energyProvenance;

  return (
    <main className="mx-auto max-w-[1000px] px-4 py-6 sm:px-6">
      <h1 className="text-xl font-semibold sm:text-2xl">Why this call?</h1>
      <p className="mt-1 text-sm text-muted-foreground">
        {selected}
        {driver.name ? ` — ${driver.name}` : ""}
        {driver.team ? `, ${driver.team}` : ""}. Open only the layers you care about.
      </p>

      <div className="panel mt-5 flex flex-wrap items-center justify-between gap-3 p-4">
        <span
          className={`data rounded-lg border px-3 py-1.5 text-sm tracking-[0.14em] ${
            rec ? POSTURE_STYLE[rec.posture] : "border-border text-muted-foreground"
          }`}
        >
          {rec?.posture ?? "NO CALL"}
        </span>
        <span className="data text-xs text-muted-foreground">
          CONFIDENCE {fmtPct(rec?.confidence)} · P(PASS) {fmtPct(rec?.passProbability)} · EV{" "}
          {fmtSignedSeconds(rec?.overtakeEv)}
        </span>
      </div>
      {rec?.reason && <p className="mt-2 text-sm text-muted-foreground">{rec.reason}</p>}

      <div className="mt-5 space-y-3">
        <Section
          open
          title="Estimated state of charge"
          summary={`${fmtPct(state?.soc)} — energy observer estimate`}
          provenance={energyProv}
        >
          <p>
            RaceIQ has no direct battery telemetry. State of charge is reconstructed from lap-time
            deltas, speed traces and the regulated per-lap energy budget, then smoothed over a
            rolling window.
          </p>
          <p>
            Trend over the last sampling window:{" "}
            {isNum(state?.socTrend) ? `${((state?.socTrend ?? 0) * 100).toFixed(1)} pt` : EMPTY}.
          </p>
        </Section>

        <Section
          title="Inferred ERS state"
          summary={`${state?.ersMode ?? EMPTY} — deploy / harvest / recharge classification`}
          provenance={energyProv}
        >
          <p>
            Mode is classified from the sign and slope of the estimated energy trace: falling fast is
            Deploy, rising slowly is Harvesting, rising fast under braking is Recharge.
          </p>
          <p>
            Clipping is flagged when the estimate saturates near the ceiling while still rising —
            energy that cannot be stored or usefully deployed. Superclipping is only reported when
            saturation persists across a full straight-mode zone.
          </p>
        </Section>

        <Section
          title="Active Aero inference"
          summary={
            state?.aeroMode ? `${state.aeroMode} MODE at this point on the lap` : "Not reported"
          }
          provenance="INFERRED"
        >
          <p>
            Straight Mode and Corner Mode are inferred from track position and speed, not read from
            the car. Active Aero zones are separate from the Overtake Detection Line and Overtake
            Activation Line and are never conflated with them.
          </p>
        </Section>

        <Section
          title="Overtake Detection and Activation"
          summary={
            state?.inDetectionWindow === undefined
              ? "Not reported"
              : state.inDetectionWindow
                ? "Inside the detection window on this lap"
                : "Outside the detection window"
          }
          provenance="INFERRED"
        >
          <p>
            On this schematic the Overtake Detection Line sits at{" "}
            {fmtPct(circuit.detectionLine)} of the lap and the Overtake Activation Line at{" "}
            {fmtPct(circuit.activationLine)}.
          </p>
          <p>
            Detection Gap to the car ahead:{" "}
            {state?.position === 1 ? "n/a — leading" : fmtSeconds(state?.gapAhead, 2)}. Overtake Mode
            is only usable between the two lines.
          </p>
        </Section>

        <Section
          title="Opponent state and trap check"
          summary={
            ahead ? `Car ahead: ${ahead.code}, ${ahead.ersMode ?? EMPTY}` : "No car in range"
          }
          provenance="INFERRED"
        >
          {ahead ? (
            <>
              <p>
                Opponent battery estimate {fmtPct(ahead.soc)}, energy state {ahead.ersMode ?? EMPTY}.
                A trap is suspected when an opponent lifts to invite a move while holding a large
                deploy reserve.
              </p>
              <p>
                Trap flag:{" "}
                {isNum(ahead.soc) && isNum(state?.soc)
                  ? ahead.soc - (state?.soc ?? 0) > 0.12
                    ? "possible — opponent holds more energy"
                    : "none detected"
                  : "not assessable without an energy estimate"}
                .
              </p>
            </>
          ) : (
            <p>Nothing within range to model.</p>
          )}
        </Section>

        <Section
          title="Pass probability and overtake EV"
          summary={`P(pass) ${fmtPct(rec?.passProbability)}, EV ${fmtSeconds(rec?.overtakeEv, 2)}`}
          provenance="INFERRED"
        >
          <p>
            P(pass) combines the detection gap, the energy edge over the opponent and whether the car
            is inside the detection window. Expected value weighs the gain of a completed move
            against the time lost on a failed one, minus the energy spent.
          </p>
          <p>Projected energy cost of the move: {fmtPoints(rec?.energyCost)}.</p>
        </Section>

        <Section
          title="FIA constraints applied"
          summary="Regulatory limits enforced before any recommendation"
          provenance="INFERRED"
        >
          {rec?.constraints?.length ? (
            <ul className="list-disc space-y-1 pl-4">
              {rec.constraints.map((c) => (
                <li key={c}>{c}</li>
              ))}
            </ul>
          ) : (
            <p>The connected data source did not report the constraints applied to this call.</p>
          )}
        </Section>

        <Section
          title="Calculation provenance"
          summary="Every input and how it was obtained"
          provenance={snapshot.positionsProvenance}
        >
          {rec?.factors?.length ? (
            <ul className="space-y-1">
              {rec.factors.map((f) => (
                <li key={f.label} className="flex items-center justify-between gap-3">
                  <span>{f.label}</span>
                  <span className="flex items-center gap-2">
                    <span className="data text-foreground">{f.value}</span>
                    <ProvenanceTag kind={f.provenance} />
                  </span>
                </li>
              ))}
            </ul>
          ) : (
            <p>No per-input provenance was reported for this call.</p>
          )}
          <p>
            Replay positions and gaps come from the connected replay source. Everything marked
            inferred is produced by the RaceIQ estimator and carries uncertainty.
          </p>
        </Section>
      </div>
    </main>
  );
}
