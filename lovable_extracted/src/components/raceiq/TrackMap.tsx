import { useLayoutEffect, useRef, useState } from "react";
import { isNum } from "@/lib/raceiq/format";
import { useRaceIQ } from "@/lib/raceiq/store";
import { ProvenanceTag } from "./ProvenanceTag";

export function TrackMap() {
  const { circuit, circuitId, snapshot, selected, rival, setSelected, driver: driverOf } =
    useRaceIQ();
  const pathRef = useRef<SVGPathElement | null>(null);
  const [geometry, setGeometry] = useState<{ id: string; length: number } | null>(null);
  const brakingZones = circuit.brakingZones ?? [];

  // Measure after commit so the geometry always matches the circuit currently drawn.
  useLayoutEffect(() => {
    const el = pathRef.current;
    if (!el) return;
    setGeometry({ id: circuitId, length: el.getTotalLength() });
  }, [circuitId]);

  const ready = geometry?.id === circuitId && geometry.length > 0;
  const len = ready ? geometry.length : 0;

  const point = (fraction?: number) => {
    const el = pathRef.current;
    if (!el || !ready || !isNum(fraction)) return null;
    const norm = ((fraction % 1) + 1) % 1;
    const p = el.getPointAtLength((1 - norm) * len);
    return { x: p.x, y: p.y };
  };

  const markerOrder = snapshot.drivers
    .slice()
    .sort((a, b) => Number(a.code === selected) - Number(b.code === selected));

  return (
    <section className="panel relative overflow-hidden p-4 sm:p-5">
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className="eyebrow">Race position</p>
          <h2 className="mt-1 text-xl font-semibold">{circuit.event}</h2>
          <p className="data mt-1 text-[10px] text-muted-foreground">
            {circuit.name} · LAP {snapshot.lap}/{snapshot.totalLaps}
          </p>
        </div>
        <ProvenanceTag kind={snapshot.positionsProvenance} />
      </div>

      <svg
        viewBox={circuit.viewBox}
        className="mt-1 h-[64vh] min-h-[460px] w-full max-h-[820px]"
        aria-label={`${circuit.name} car position map`}
      >
        <path
          key={circuitId}
          ref={pathRef}
          d={circuit.path}
          fill="none"
          stroke="var(--track)"
          strokeWidth={22}
          strokeLinejoin="round"
          strokeLinecap="round"
          opacity={0.20}
          vectorEffect="non-scaling-stroke"
        />
        <path
          d={circuit.path}
          fill="none"
          stroke="var(--muted-foreground)"
          strokeWidth={8}
          strokeLinejoin="round"
          strokeLinecap="round"
          opacity={0.50}
          vectorEffect="non-scaling-stroke"
        />
        {brakingZones.map((zone) => (
          <path
            key={zone.label}
            d={circuit.path}
            fill="none"
            pathLength={1}
            stroke="var(--primary)"
            strokeWidth={8}
            strokeDasharray={`${zone.width} ${1 - zone.width}`}
            strokeDashoffset={-((1 - zone.at - zone.width / 2 + 1) % 1)}
            strokeLinecap="round"
            opacity={0.46}
            vectorEffect="non-scaling-stroke"
            pointerEvents="none"
          />
        ))}
        {brakingZones.map((zone) => {
          const p = point(zone.at);
          if (!p) return null;
          return (
            <g key={zone.label} pointerEvents="none" transform={`translate(${p.x}, ${p.y})`}>
              <text
                x={10}
                y={-8}
                className="data"
                fontSize={8}
                fontWeight={700}
                fill="var(--muted-foreground)"
              >
                {zone.label}
              </text>
            </g>
          );
        })}
        {markerOrder.map((d) => {
          const p = point(d.lapFraction);
          if (!p) return null;
          const driver = driverOf(d.code);
          const isSelected = d.code === selected;
          const isRival = d.code === rival;
          const isTracked = Boolean(driver.tracked);

          return (
            <g
              key={d.code}
              onClick={() => setSelected(d.code)}
              className="cursor-pointer focus:outline-none"
              aria-label={`${driver.name ?? d.code}, position ${d.position}`}
              role="button"
              tabIndex={0}
              onKeyDown={(event) => {
                if (event.key === "Enter" || event.key === " ") setSelected(d.code);
              }}
              transform={`translate(${p.x}, ${p.y})`}
            >
              {/* Rival indicator: crisp dashed ring */}
              {isRival && !isSelected && (
                <circle
                  r={8}
                  fill="none"
                  stroke="var(--foreground)"
                  strokeWidth={1.5}
                  strokeDasharray="2.5 1.5"
                  opacity={0.85}
                />
              )}

              {/* Selected driver: outer solid ring */}
              {isSelected && (
                <circle
                  r={9.5}
                  fill="none"
                  stroke="var(--foreground)"
                  strokeWidth={1.8}
                  opacity={0.95}
                />
              )}

              {/* Normal car marker: small circle with driver team color */}
              <circle
                r={isSelected ? 6.5 : isTracked ? 5.5 : 4.5}
                fill={driver.color}
                stroke="var(--background)"
                strokeWidth={1.5}
              />

              {/* Selected driver technical rectangular label */}
              {isSelected && (
                <g transform="translate(0, -22)" pointerEvents="none">
                  <rect
                    x={-17}
                    y={-9}
                    width={34}
                    height={16}
                    rx={3}
                    fill="var(--foreground)"
                  />
                  <text
                    y={3}
                    textAnchor="middle"
                    className="data"
                    fontSize={10}
                    fontWeight={800}
                    fill="var(--background)"
                  >
                    {d.code}
                  </text>
                </g>
              )}
            </g>
          );
        })}
      </svg>

      <p className="data absolute bottom-4 left-1/2 -translate-x-1/2 whitespace-nowrap text-[9px] text-muted-foreground">
        RED = MAJOR BRAKING · {snapshot.positionsProvenance} POSITIONS · TRACK CC BY 4.0
      </p>
    </section>
  );
}
