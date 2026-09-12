import { createFileRoute } from "@tanstack/react-router";
import { useState } from "react";
import { ProvenanceTag } from "@/components/raceiq/ProvenanceTag";
import { POSTURE_STYLE } from "@/components/raceiq/MatchupCard";
import type { Posture } from "@/lib/raceiq/contracts";
import {
  EMPTY,
  fmtClock,
  fmtGap,
  fmtPct,
  fmtPoints,
  fmtSeconds,
  fmtPosition,
} from "@/lib/raceiq/format";
import { useRaceIQ } from "@/lib/raceiq/store";

export const Route = createFileRoute("/what-if")({
  head: () => ({
    meta: [
      { title: "What If — RaceIQ" },
      {
        name: "description",
        content:
          "Pause the replay and ask what would have happened. Every branch is labelled projected, and history stays untouched.",
      },
      { property: "og:title", content: "What If — RaceIQ" },
      {
        property: "og:description",
        content: "Counterfactual race branches seeded from an untouched replay state.",
      },
    ],
  }),
  component: WhatIf,
});

const ACTIONS: Posture[] = ["ATTACK", "HOLD", "DEFEND", "HARVEST"];

function WhatIf() {
  const {
    snapshot,
    circuit,
    selected,
    setSelected,
    pause,
    playing,
    time,
    driver: driverOf,
    stateOf,
    whatIf,
  } = useRaceIQ();
  const [action, setAction] = useState<Posture>("ATTACK");
  const branch = whatIf(selected, action);
  const state = stateOf(selected);
  const driver = driverOf(selected);
  const ahead = snapshot.drivers.find((d) => d.position === (state?.position ?? 0) - 1);

  return (
    <main className="mx-auto max-w-[1200px] px-4 py-6 sm:px-6">
      <h1 className="text-xl font-semibold sm:text-2xl">What if?</h1>
      <p className="mt-1 max-w-2xl text-sm text-muted-foreground">
        Freeze a moment from the replay, change one decision, and see the projected outcome. The
        replay itself is never rewritten.
      </p>

      <div className="mt-5 grid gap-4 lg:grid-cols-2">
        <section className="panel p-4">
          <div className="flex items-center justify-between gap-2">
            <p className="eyebrow">Frozen race state (seed)</p>
            <ProvenanceTag kind={snapshot.positionsProvenance} />
          </div>
          <dl className="mt-3 grid grid-cols-2 gap-3">
            {[
              { k: "Circuit", v: circuit.event },
              { k: "Lap", v: `${snapshot.lap}/${snapshot.totalLaps}` },
              { k: "Race clock", v: fmtClock(time) },
              { k: "Driver", v: `${selected}${driver.team ? ` — ${driver.team}` : ""}` },
              { k: "Position", v: fmtPosition(state?.position) },
              { k: "Gap ahead", v: state?.position === 1 ? EMPTY : fmtGap(state?.gapAhead, 2) },
              { k: "Battery (est.)", v: fmtPct(state?.soc) },
              { k: "Car ahead", v: ahead ? ahead.code : "none" },
            ].map((i) => (
              <div key={i.k}>
                <dt className="text-[11px] text-muted-foreground">{i.k}</dt>
                <dd className="data text-sm">{i.v}</dd>
              </div>
            ))}
          </dl>
          <div className="mt-4 flex flex-wrap items-center gap-2 border-t border-border pt-3">
            <select
              value={selected}
              onChange={(e) => setSelected(e.target.value)}
              aria-label="Driver"
              className="data rounded-md border border-border bg-surface-raised px-2 py-1 text-xs"
            >
              {snapshot.drivers.map((d) => (
                <option key={d.code} value={d.code}>
                  P{d.position} {d.code}
                </option>
              ))}
            </select>
            <button
              type="button"
              onClick={pause}
              disabled={!playing}
              className="data rounded-md border border-border px-2 py-1 text-xs text-muted-foreground transition-colors hover:bg-accent disabled:opacity-40"
            >
              {playing ? "FREEZE REPLAY" : "REPLAY FROZEN"}
            </button>
          </div>
        </section>

        <section className="panel p-4">
          <div className="flex items-center justify-between gap-2">
            <p className="eyebrow">Counterfactual branch</p>
            <ProvenanceTag kind="PROJECTED" />
          </div>
          <p className="mt-2 text-sm">
            What if {selected} chose <span className="text-primary">{action}</span> here?
          </p>
          <div className="mt-3 flex flex-wrap gap-2">
            {ACTIONS.map((a) => (
              <button
                key={a}
                type="button"
                onClick={() => setAction(a)}
                className={`data rounded-lg border px-2.5 py-1 text-xs tracking-[0.12em] transition-colors ${
                  action === a ? POSTURE_STYLE[a] : "border-border text-muted-foreground hover:bg-accent/50"
                }`}
              >
                {a}
              </button>
            ))}
          </div>

          <dl className="mt-4 grid grid-cols-2 gap-3">
            {[
              { k: "Projected position", v: fmtPosition(branch?.projectedPosition) },
              { k: "Projected gap", v: fmtSeconds(branch?.projectedGap, 2) },
              { k: "Projected battery", v: fmtPct(branch?.projectedSoc) },
              {
                k: "Energy cost",
                v:
                  typeof branch?.energyCost === "number"
                    ? fmtPoints(-branch.energyCost)
                    : EMPTY,
              },
              { k: "Risk", v: branch?.risk ?? EMPTY },
              { k: "Confidence", v: fmtPct(branch?.confidence) },
            ].map((i) => (
              <div key={i.k}>
                <dt className="text-[11px] text-muted-foreground">{i.k}</dt>
                <dd className="data text-sm text-projected">{i.v}</dd>
              </div>
            ))}
          </dl>

          <div className="mt-4 space-y-2 border-t border-border pt-3 text-xs text-muted-foreground">
            {branch?.outcome ? (
              <p>{branch.outcome}</p>
            ) : (
              <p>No counterfactual branch available from the connected data source for this state.</p>
            )}
            {branch?.opponentResponse && <p>{branch.opponentResponse}</p>}
          </div>
        </section>
      </div>

      <p className="data mt-4 rounded-xl border border-projected/40 bg-projected/10 p-3 text-[11px] text-projected">
        BRANCH SEED · {(branch?.seed.circuitId ?? snapshot.circuitId).toUpperCase()} / LAP{" "}
        {branch?.seed.lap ?? snapshot.lap} / T{(branch?.seed.time ?? snapshot.time).toFixed(1)}s /{" "}
        {branch?.seed.driver ?? selected} {fmtPosition(branch?.seed.position ?? state?.position)} —
        the seed is immutable and the historical replay is unchanged. Counterfactual branches are
        pre-computed during RaceIQ data preparation from the replay state; clicking an action does
        not run a live backend simulation.
      </p>
    </main>
  );
}
