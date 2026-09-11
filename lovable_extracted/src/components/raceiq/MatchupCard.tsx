import { Link } from "@tanstack/react-router";
import type { Posture } from "@/lib/raceiq/contracts";
import { EMPTY, fmtPct, fmtSeconds, isNum, pctWidth } from "@/lib/raceiq/format";
import { useRaceIQ } from "@/lib/raceiq/store";
import { ProvenanceTag } from "./ProvenanceTag";

export const POSTURE_STYLE: Record<Posture, string> = {
  ATTACK: "text-attack border-attack/50 bg-attack/10",
  HOLD: "text-hold border-hold/50 bg-hold/10",
  DEFEND: "text-defend border-defend/50 bg-defend/10",
  HARVEST: "text-harvest border-harvest/50 bg-harvest/10",
};

export function MatchupCard() {
  const { selected, rival, driver: driverOf, stateOf, recommendationFor } = useRaceIQ();
  const a = stateOf(selected);
  const b = stateOf(rival);
  const da = driverOf(selected);
  const db = driverOf(rival);
  const rec = recommendationFor(selected);
  const socDelta =
    isNum(a?.soc) && isNum(b?.soc) ? Math.round(((a?.soc ?? 0) - (b?.soc ?? 0)) * 100) : undefined;
  const gap =
    isNum(a?.gapToLeader) && isNum(b?.gapToLeader)
      ? Math.abs((a?.gapToLeader ?? 0) - (b?.gapToLeader ?? 0))
      : undefined;

  return (
    <div className="panel p-4">
      <div className="flex items-center justify-between gap-2">
        <p className="eyebrow">Head to head</p>
        <ProvenanceTag kind="INFERRED" />
      </div>

      <div className="mt-3 grid grid-cols-[minmax(0,1fr)_auto_minmax(0,1fr)] items-center gap-3">
        <div className="flex min-w-0 items-center gap-2">
          <span className="data grid h-7 w-7 shrink-0 place-items-center rounded-md border border-border text-[11px]">
            {a?.position ?? EMPTY}
          </span>
          <span className="min-w-0">
            <span className="data block truncate text-sm font-semibold">{selected}</span>
            <span className="block truncate text-[11px] text-muted-foreground">{da.team}</span>
          </span>
        </div>
        <div className="text-center">
          <p className="eyebrow">ΔSoC</p>
          <p
            className={`data text-2xl font-semibold ${(socDelta ?? 0) >= 0 ? "text-harvest" : "text-primary"}`}
          >
            {isNum(socDelta) ? `${socDelta >= 0 ? "+" : ""}${socDelta}%` : EMPTY}
          </p>
        </div>
        <div className="flex min-w-0 items-center justify-end gap-2 text-right">
          <span className="min-w-0">
            <span className="data block truncate text-sm font-semibold">{rival}</span>
            <span className="block truncate text-[11px] text-muted-foreground">{db.team}</span>
          </span>
          <span className="data grid h-7 w-7 shrink-0 place-items-center rounded-md border border-border text-[11px]">
            {b?.position ?? EMPTY}
          </span>
        </div>
      </div>

      <div className="mt-3 grid grid-cols-[minmax(0,1fr)_auto_minmax(0,1fr)] items-center gap-3">
        <div className="flex items-center gap-2">
          <span className="flex h-2 flex-1 overflow-hidden rounded-full bg-muted">
            <span
              className="h-full rounded-full"
              style={{ width: `${pctWidth(a?.soc)}%`, backgroundColor: da.color }}
            />
          </span>
          <span className="data text-xs">{fmtPct(a?.soc)}</span>
        </div>
        <div className="text-center">
          <p className="eyebrow">Gap</p>
          <p className="data text-sm">{fmtSeconds(gap)}</p>
        </div>
        <div className="flex items-center gap-2">
          <span className="data text-xs">{fmtPct(b?.soc)}</span>
          <span className="flex h-2 flex-1 overflow-hidden rounded-full bg-muted">
            <span
              className="h-full rounded-full"
              style={{ width: `${pctWidth(b?.soc)}%`, backgroundColor: db.color }}
            />
          </span>
        </div>
      </div>

      <div className="mt-4 flex flex-wrap items-center justify-between gap-2 border-t border-border pt-3">
        {rec ? (
          <span
            className={`data inline-flex items-center gap-2 rounded-lg border px-2.5 py-1 text-xs tracking-[0.12em] ${POSTURE_STYLE[rec.posture]}`}
          >
            <span className="h-1.5 w-1.5 rounded-full bg-current" />
            {rec.posture}
          </span>
        ) : (
          <span className="data inline-flex items-center gap-2 rounded-lg border border-border px-2.5 py-1 text-xs tracking-[0.12em] text-muted-foreground">
            NO CALL
          </span>
        )}
        <div className="flex gap-2">
          <Link
            to="/why"
            className="data rounded-lg border border-border px-2.5 py-1 text-xs text-muted-foreground transition-colors hover:bg-accent"
          >
            WHY?
          </Link>
          <Link
            to="/what-if"
            className="data rounded-lg border border-primary/50 bg-primary/10 px-2.5 py-1 text-xs text-primary transition-colors hover:bg-primary/20"
          >
            WHAT IF?
          </Link>
        </div>
      </div>
      {rec?.reason && <p className="mt-2 text-xs text-muted-foreground">{rec.reason}</p>}
    </div>
  );
}
