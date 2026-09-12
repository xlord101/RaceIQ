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
    <div className="panel grid gap-3 p-2.5 sm:px-4 sm:py-2.5 lg:grid-cols-[auto_minmax(0,1fr)_auto] lg:items-center">
      {/* LEFT: PLAY/PAUSE, LAP x/y, RACE CLOCK */}
      <div className="flex items-center gap-3">
        <button
          type="button"
          onClick={toggle}
          className="data w-18 rounded border border-border bg-surface-raised px-2.5 py-1 text-[11px] font-semibold tracking-wider text-foreground transition-colors hover:border-primary/50 hover:bg-primary/10"
        >
          {playing ? "PAUSE" : "PLAY"}
        </button>
        <div className="flex items-center gap-2 text-xs">
          <span className="data font-semibold text-foreground">
            LAP {snapshot.lap}/{snapshot.totalLaps}
          </span>
          <span className="text-border">·</span>
          <span className="data text-muted-foreground">
            {fmtClock(time)}
          </span>
        </div>
      </div>

      {/* CENTER: REPLAY TIMELINE */}
      <div className="flex items-center px-1">
        <input
          type="range"
          min={0}
          max={duration}
          step={1}
          value={time}
          onChange={(e) => setTime(Number(e.target.value))}
          aria-label="Replay time"
          className="h-1.5 w-full cursor-pointer appearance-none rounded bg-muted accent-primary"
        />
      </div>

      {/* RIGHT: CIRCUIT SELECTOR */}
      <div className="flex items-center justify-end gap-2">
        <span className="eyebrow text-[10px] hidden sm:inline">CIRCUIT</span>
        <select
          value={circuitId}
          onChange={(e) => setCircuit(e.target.value)}
          aria-label="Circuit selector"
          className="data rounded border border-border bg-surface-raised px-2.5 py-1 text-[11px] font-medium text-foreground focus:outline-none"
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
