import { useId, useLayoutEffect, useRef, useState } from "react";
import { isNum } from "@/lib/raceiq/format";
import { useRaceIQ } from "@/lib/raceiq/store";
import { ProvenanceTag } from "./ProvenanceTag";

export function TrackMap() {
  const { circuit, circuitId, snapshot, selected, rival, playing, setSelected, driver: driverOf } =
    useRaceIQ();
  const pathRef = useRef<SVGPathElement | null>(null);
  const [geometry, setGeometry] = useState<{ id: string; length: number } | null>(null);
  const glowId = useId().replaceAll(":", "");
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
    const p = el.getPointAtLength(((1 - fraction) % 1) * len);
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
          <p className="data mt-1 text-[10px] text-muted-foreground">{circuit.name} · LAP {snapshot.lap}/{snapshot.totalLaps}</p>
        </div>
        <ProvenanceTag kind={snapshot.positionsProvenance} />
      </div>

      <svg viewBox={circuit.viewBox} className="mt-1 h-[64vh] min-h-[460px] w-full max-h-[820px]" aria-label={`${circuit.name} car position map`}>
        <defs>
          <filter id={glowId} x="-100%" y="-100%" width="300%" height="300%">
            <feGaussianBlur stdDeviation="5" result="blur" />
            <feMerge><feMergeNode in="blur" /><feMergeNode in="SourceGraphic" /></feMerge>
          </filter>
        </defs>
        <path
          key={circuitId}
          ref={pathRef}
          d={circuit.path}
          fill="none"
          stroke="var(--track)"
          strokeWidth={24}
          strokeLinejoin="round"
          strokeLinecap="round"
          opacity={0.22}
          vectorEffect="non-scaling-stroke"
        />
        <path
          d={circuit.path}
          fill="none"
          stroke="var(--muted-foreground)"
          strokeWidth={10}
          strokeLinejoin="round"
          strokeLinecap="round"
          opacity={0.52}
          vectorEffect="non-scaling-stroke"
        />
        {brakingZones.map((zone) => (
          <path
            key={zone.label}
            d={circuit.path}
            fill="none"
            pathLength={1}
            stroke="var(--primary)"
            strokeWidth={10}
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
            <g key={zone.label} pointerEvents="none">
              <text
                x={p.x + 12}
                y={p.y - 10}
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
                style={{
                  transform: `translate(${p.x}px, ${p.y}px)`,
                  transition: playing ? "transform 120ms linear" : "transform 180ms ease-out",
                }}
              >
                {(isSelected || isRival) && (
                  <circle
                    r={isSelected ? 11 : 8}
                    fill="var(--background)"
                    stroke={isSelected ? "var(--foreground)" : driver.color}
                    strokeWidth={isSelected ? 2.5 : 2}
                    opacity={0.95}
                    style={{ filter: isSelected ? `url(#${glowId})` : undefined }}
                  />
                )}
                <circle
                  r={isSelected ? 7 : isTracked ? 5.5 : 4.5}
                  fill={driver.color}
                  stroke="var(--background)"
                  strokeWidth={1.5}
                />
                {isSelected && (
                  <g transform="translate(0 -30)" pointerEvents="none">
                    <path d="M -22 -14 H 22 Q 27 -14 27 -9 V 7 Q 27 12 22 12 H 4 L 0 18 L -4 12 H -22 Q -27 12 -27 7 V -9 Q -27 -14 -22 -14 Z" fill="var(--foreground)" />
                    <text y={2} textAnchor="middle" className="data" fontSize={11} fontWeight={800} fill="var(--background)">
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
