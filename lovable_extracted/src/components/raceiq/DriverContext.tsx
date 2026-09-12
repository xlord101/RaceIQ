import type { RaceIQDriverState } from "@/lib/raceiq/contracts";
import { EMPTY, fmtGap, fmtPct } from "@/lib/raceiq/format";
import { useRaceIQ } from "@/lib/raceiq/store";
import { POSTURE_STYLE } from "./MatchupCard";
import { ProvenanceTag } from "./ProvenanceTag";

function tyreLabel(d: RaceIQDriverState | undefined): string {
  if (!d?.tyre?.compound) return EMPTY;
  const c = d.tyre.compound.toUpperCase();
  const letter =
    ({ SOFT: "S", MEDIUM: "M", HARD: "H", INTERMEDIATE: "I", WET: "W" } as Record<string, string>)[c] ??
    c.charAt(0);
  const age = typeof d.tyre.ageLaps === "number" ? `${Math.round(d.tyre.ageLaps)}L` : "";
  return age ? `${letter} ${age}` : letter;
}

function ContextRow({
  role,
  d,
  team,
  color,
  dominant = false,
}: {
  role: string;
  d: RaceIQDriverState | undefined;
  team: string;
  color: string;
  dominant?: boolean;
}) {
  const gap = !d ? EMPTY : d.position === 1 ? "LEADER" : fmtGap(d.gapAhead, 1);
  const soc = d ? fmtPct(d.soc) : EMPTY;
  const ers = d?.ersMode ?? EMPTY;
  const tyreTitle =
    d?.tyre?.compound
      ? `${d.tyre.compound} · ${typeof d.tyre.ageLaps === "number" ? `${Math.round(d.tyre.ageLaps)} laps` : "age unavailable"}`
      : "Tyre data unavailable";
  return (
    <div
      className={`grid grid-cols-[auto_auto_minmax(0,1fr)_auto_auto_auto_auto] items-center gap-2 rounded border px-2 py-1.5 text-left ${
        dominant ? "border-primary/70 bg-primary/10" : "border-border bg-surface-raised"
      }`}
    >
      <span className={`rounded bg-muted/40 px-1.5 py-0.5 text-[9px] font-bold tracking-wider ${
        dominant ? "text-primary" : "text-muted-foreground"
      }`}>
        {role}
      </span>
      <span className="grid h-6 w-6 place-items-center rounded-md border border-border text-[11px] font-semibold">
        {d ? d.position : EMPTY}
      </span>
      <span className="flex min-w-0 items-center gap-1.5">
        <span className="h-3 w-[3px] shrink-0 rounded-sm" style={{ backgroundColor: color }} />
        <span className="truncate text-sm font-semibold">{d ? d.code : "—"}</span>
        <span className="truncate text-[10px] text-muted-foreground">{team}</span>
        {d?.tyre?.compound && (
          <span className="text-[10px] text-muted-foreground" title={tyreTitle}>
            {tyreLabel(d)}
          </span>
        )}
      </span>
      <span className="text-[11px] font-mono text-muted-foreground">{gap}</span>
      <span
        className="data text-[10px] text-muted-foreground"
        title={ers === EMPTY ? "ERS mode unavailable" : "Estimated ERS mode (INFERRED)"}
      >
        {ers}
      </span>
      <span className="data text-[11px]" title="Estimated SoC (INFERRED)">{soc}</span>
      <span className="sr-only">{d?.position ?? EMPTY}</span>
    </div>
  );
}

/**
 * Primary Haas workflow: pick the driver, and RaceIQ automatically shows the
 * immediate car ahead / behind from the ACTUAL current race order, plus the
 * RaceIQ decision. Opponents are never picked by hand here.
 */
export function DriverContext() {
  const {
    selected,
    aheadOf,
    behindOf,
    driver: driverOf,
    stateOf,
    recommendationFor,
    snapshot,
  } = useRaceIQ();

  const state = stateOf(selected);
  const driver = driverOf(selected);
  const ahead = aheadOf(selected);
  const behind = behindOf(selected);
  const rec = recommendationFor(selected);
  const aheadDriver = ahead ? driverOf(ahead.code) : undefined;
  const behindDriver = behind ? driverOf(behind.code) : undefined;

  return (
    <section className="panel border-primary/30 p-4">
      <div className="flex items-center justify-between gap-2">
        <p className="eyebrow text-primary">Current driver — {selected}</p>
        <ProvenanceTag kind={snapshot.positionsProvenance} />
      </div>

      <div className="mt-3 flex flex-col gap-2">
        <ContextRow
          role="AHEAD"
          d={ahead}
          team={aheadDriver?.team ?? "—"}
          color={aheadDriver?.color ?? "#8c8f93"}
        />
        <ContextRow
          role="SELECTED"
          d={state}
          team={driver.team ?? "—"}
          color={driver.color ?? "#E8002D"}
          dominant
        />
        <ContextRow
          role="BEHIND"
          d={behind}
          team={behindDriver?.team ?? "—"}
          color={behindDriver?.color ?? "#8c8f93"}
        />
      </div>

      <div className="mt-3 flex flex-wrap items-center justify-between gap-2 border-t border-border pt-3">
        <span className="text-[11px] text-muted-foreground">RaceIQ call</span>
        {rec ? (
          <span
            className={`data inline-flex items-center gap-2 rounded border px-2.5 py-1 text-xs tracking-[0.12em] ${POSTURE_STYLE[rec.posture]}`}
          >
            <span className="h-1.5 w-1.5 rounded-full bg-current" />
            {rec.posture}
          </span>
        ) : (
          <span className="data inline-flex items-center gap-2 rounded border border-border px-2.5 py-1 text-xs tracking-[0.12em] text-muted-foreground">
            NO CALL
          </span>
        )}
      </div>
      {rec?.headline && <p className="mt-1 text-xs text-muted-foreground">{rec.headline}</p>}
      {rec?.reason && <p className="mt-1 text-[11px] leading-snug text-muted-foreground">{rec.reason}</p>}
    </section>
  );
}
