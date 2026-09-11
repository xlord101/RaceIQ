import type { Provenance } from "@/lib/raceiq/contracts";

const COPY: Record<Provenance, { label: string; hint: string; cls: string }> = {
  SAMPLE: {
    label: "SAMPLE",
    hint: "Demo replay data — stands in until a recorded session is connected.",
    cls: "text-actual border-actual/40 bg-actual/10",
  },
  ACTUAL: {
    label: "ACTUAL",
    hint: "Recorded in the session. Not changed by RaceIQ.",
    cls: "text-actual border-actual/40 bg-actual/10",
  },
  INFERRED: {
    label: "INFERRED",
    hint: "Estimated by RaceIQ. Not directly measured.",
    cls: "text-inferred border-inferred/40 bg-inferred/10",
  },
  PROJECTED: {
    label: "PROJECTED",
    hint: "A what-if projection. This never happened.",
    cls: "text-projected border-projected/40 bg-projected/10",
  },
};

export function ProvenanceTag({
  kind,
  className = "",
}: {
  kind: Provenance;
  className?: string;
}) {
  const c = COPY[kind];
  return (
    <span
      title={c.hint}
      className={`data inline-flex shrink-0 items-center rounded-md border px-1.5 py-0.5 text-[9px] tracking-[0.14em] ${c.cls} ${className}`}
    >
      {c.label}
    </span>
  );
}

export function ProvenanceLegend({
  kinds = ["SAMPLE", "INFERRED", "PROJECTED"],
}: {
  kinds?: Provenance[];
}) {
  return (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-2 text-xs text-muted-foreground">
      {kinds.map((k) => (
        <span key={k} className="flex items-center gap-2">
          <ProvenanceTag kind={k} />
          {COPY[k].hint}
        </span>
      ))}
    </div>
  );
}
