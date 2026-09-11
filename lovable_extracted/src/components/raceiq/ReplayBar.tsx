import { fmtClock } from "@/lib/raceiq/format";
import { useRaceIQ } from "@/lib/raceiq/store";

export function ReplayBar() {
  const {
    circuitId,
    circuits,
    setCircuit,
    time,
    setTime,
    duration,
    playing,
    toggle,
    snapshot,
  } = useRaceIQ();

  return (
    <div className="panel grid gap-3 p-3 lg:grid-cols-[auto_minmax(0,1fr)_auto] lg:items-center">
      <div className="flex items-center gap-2">
        <button
          type="button"
          onClick={toggle}
          className="data w-20 rounded-lg border border-primary/50 bg-primary/15 px-3 py-1.5 text-xs tracking-[0.14em] text-primary transition-colors hover:bg-primary/25"
        >
          {playing ? "PAUSE" : "PLAY"}
        </button>
        <span className="data text-xs text-muted-foreground">
          LAP {snapshot.lap}/{snapshot.totalLaps} · {fmtClock(time)}
        </span>
      </div>

      <input
        type="range"
        min={0}
        max={duration}
        step={1}
        value={time}
        onChange={(e) => setTime(Number(e.target.value))}
        aria-label="Replay time"
        className="h-1.5 w-full cursor-pointer appearance-none rounded-full bg-muted accent-primary"
      />

      <div className="flex flex-wrap items-center justify-end gap-2">
        <select
          value={circuitId}
          onChange={(e) => setCircuit(e.target.value)}
          aria-label="Circuit"
          className="data rounded-md border border-border bg-surface-raised px-2 py-1 text-[11px]"
        >
          {circuits.map((c) => (
            <option key={c.id} value={c.id}>
              {c.event}
            </option>
          ))}
        </select>
      </div>
    </div>
  );
}
