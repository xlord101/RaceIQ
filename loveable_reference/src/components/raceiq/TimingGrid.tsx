import type { RaceIQDriverState } from "@/lib/raceiq/contracts";
import { fmtPct, pctWidth } from "@/lib/raceiq/format";
import { useRaceIQ } from "@/lib/raceiq/store";
import { ProvenanceTag } from "./ProvenanceTag";

function Row({ d }: { d: RaceIQDriverState }) {
  const { selected, rival, setSelected, driver: driverOf } = useRaceIQ();
  const driver = driverOf(d.code);
  const isSelected = d.code === selected;
  const isRival = d.code === rival;
  return (
    <button
      type="button"
      onClick={() => setSelected(d.code)}
      className={`grid w-full grid-cols-[1.6rem_0.15rem_5.5rem_minmax(0,1fr)_3rem_2.4rem] items-center gap-1.5 rounded-lg border px-2 py-1 text-left transition-colors sm:gap-2 ${
        isSelected
          ? "border-primary/60 bg-primary/10"
          : isRival
            ? "border-foreground/30 bg-accent/40"
            : "border-transparent hover:bg-accent/40"
      }`}
    >
      <span className="data text-right text-[11px] text-muted-foreground">{d.position}</span>
      <span className="h-4 w-[3px] rounded-full" style={{ backgroundColor: driver.color }} />
      <span className="data flex min-w-0 items-center gap-1.5 text-[12px] font-medium">
        <span className="truncate">{d.code}</span>
        {driver.tracked && (
          <span className="data rounded bg-primary/20 px-1 text-[8px] tracking-widest text-primary">
            {(driver.team ?? "TRACKED").toUpperCase()}
          </span>
        )}
      </span>
      <span className="data text-right text-[10px] text-muted-foreground">
        {d.position === 1 ? "—" : typeof d.gapAhead === "number" ? `+${d.gapAhead.toFixed(1)}` : "—"}
      </span>
      <span className="flex h-1.5 overflow-hidden rounded-full bg-muted">
        <span
          className="h-full rounded-full"
          style={{ width: `${pctWidth(d.soc)}%`, backgroundColor: driver.color }}
        />
      </span>
      <span className="data text-right text-[11px]">{fmtPct(d.soc)}</span>
    </button>
  );
}

export function TimingGrid() {
  const { snapshot } = useRaceIQ();
  const half = Math.ceil(snapshot.drivers.length / 2);
  const columns = [snapshot.drivers.slice(0, half), snapshot.drivers.slice(half)];

  return (
    <div className="panel p-4">
      <div className="flex items-center justify-between gap-2">
        <p className="eyebrow">Grid — {snapshot.drivers.length} drivers</p>
        <div className="flex items-center gap-1.5">
          <ProvenanceTag kind={snapshot.positionsProvenance} />
          <ProvenanceTag kind={snapshot.energyProvenance} />
        </div>
      </div>
      <p className="mt-1 text-[11px] text-muted-foreground">
        Tap a driver to compare. Gap is replay data, battery % is a RaceIQ estimate.
      </p>
      <div className="mt-3 grid gap-x-4 gap-y-0.5 lg:grid-cols-2">
        {columns.map((col, i) => (
          <div key={i} className="space-y-0.5">
            {col.map((d) => (
              <Row key={d.code} d={d} />
            ))}
          </div>
        ))}
      </div>
    </div>
  );
}
