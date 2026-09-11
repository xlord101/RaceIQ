import { fmtGap, fmtPct, pctWidth } from "@/lib/raceiq/format";
import { useRaceIQ } from "@/lib/raceiq/store";
import { POSTURE_STYLE } from "./MatchupCard";
import { ProvenanceTag } from "./ProvenanceTag";

export function HaasPanel() {
  const { snapshot, selected, setSelected, adapter, driver: driverOf, stateOf, recommendationFor } =
    useRaceIQ();

  const trackedCodes = snapshot.drivers
    .filter((d) => adapter.driver(d.code)?.tracked)
    .map((d) => d.code);

  return (
    <section className="panel border-primary/30 p-4">
      <div className="flex items-center justify-between gap-2">
        <p className="eyebrow text-primary">Haas — RaceIQ call</p>
        <ProvenanceTag kind="INFERRED" />
      </div>
      <div className="mt-3 grid gap-3 sm:grid-cols-2">
        {trackedCodes.map((code) => {
          const driver = driverOf(code);
          const state = stateOf(code);
          const rec = recommendationFor(code);
          const active = selected === code;
          return (
            <button
              key={code}
              type="button"
              onClick={() => setSelected(code)}
              className={`group relative min-h-44 overflow-hidden rounded-lg border p-3 text-left transition-colors ${
                active ? "border-primary/60 bg-primary/10" : "border-border bg-surface-raised hover:bg-accent/50"
              }`}
            >
              {driver.image && (
                <img
                  src={driver.image}
                  alt={`${driver.name ?? code} in the 2026 Haas race car`}
                  loading="lazy"
                  width={1440}
                  height={810}
                  className="absolute inset-0 h-full w-full object-cover opacity-55 transition duration-300 group-hover:scale-[1.02] group-hover:opacity-65"
                />
              )}
              <span className="absolute inset-0 bg-gradient-to-t from-surface via-surface/75 to-transparent" />
              <div className="relative z-10 flex min-h-36 flex-col justify-between">
                <div className="flex items-start justify-between gap-2">
                  <div className="min-w-0">
                    <p className="data text-xs text-primary">
                      {(driver.team ?? "").toUpperCase() || "TEAM"} · {code}
                    </p>
                    <p className="mt-0.5 truncate text-sm font-semibold text-foreground">
                      {driver.name ?? code}
                    </p>
                  </div>
                  <span className="data rounded border border-foreground/20 bg-background/60 px-2 py-1 text-sm backdrop-blur-sm">
                    {state ? `P${state.position}` : "—"}
                  </span>
                </div>

                <div>
                  <div className="mb-2 flex items-end justify-between gap-2">
                    <span className="data text-xs text-muted-foreground">
                      {state?.position === 1
                        ? "LEADING"
                        : `${fmtGap(state?.gapAhead)} AHEAD`}
                    </span>
                    <span className="data text-xs">SoC {fmtPct(state?.soc)}</span>
                  </div>
                  <span className="flex h-1.5 overflow-hidden rounded-full bg-muted/80">
                    <span
                      className="h-full rounded-full bg-foreground/80"
                      style={{ width: `${pctWidth(state?.soc)}%` }}
                    />
                  </span>
                  <div className="mt-2 flex items-center justify-between gap-2">
                    <span className="data text-[10px] text-muted-foreground">
                      {state?.ersMode ? `${state.ersMode} · ${snapshot.energyProvenance}` : "—"}
                    </span>
                    {rec && (
                      <span
                        className={`data rounded border px-2 py-1 text-xs font-semibold ${POSTURE_STYLE[rec.posture]}`}
                      >
                        {rec.posture}
                      </span>
                    )}
                  </div>
                </div>
              </div>
            </button>
          );
        })}
      </div>
      <p className="mt-2 text-[9px] text-muted-foreground">Driver imagery: © TGR Haas F1 Team</p>
    </section>
  );
}
