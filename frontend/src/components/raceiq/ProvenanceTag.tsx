import type { Provenance } from "@/lib/raceiq/contracts";

const DEFAULT_COPY = {
  label: "INFERRED",
  hint: "Estimated or derived by RaceIQ.",
  cls: "text-inferred border-inferred/40 bg-inferred/10",
};

const COPY: Record<string, { label: string; hint: string; cls: string }> = {
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
  OBSERVED: {
    label: "OBSERVED",
    hint: "Directly observed from telemetry or race timing.",
    cls: "text-actual border-actual/40 bg-actual/10",
  },
  DERIVED: {
    label: "DERIVED",
    hint: "Calculated deterministically from observations.",
    cls: "text-actual border-actual/40 bg-actual/10",
  },
  INFERRED: {
    label: "INFERRED",
    hint: "Estimated by RaceIQ observer or model. Not directly measured.",
    cls: "text-inferred border-inferred/40 bg-inferred/10",
  },
  PROJECTED: {
    label: "PROJECTED",
    hint: "A what-if projection. This never happened.",
    cls: "text-projected border-projected/40 bg-projected/10",
  },
  COUNTERFACTUAL: {
    label: "COUNTERFACTUAL",
    hint: "Counterfactual branch seeded from an immutable historical state.",
    cls: "text-projected border-projected/40 bg-projected/10",
  },
};

export function ProvenanceTag({
  kind,
  className = "",
}: {
  kind: Provenance | string;
  className?: string;
}) {
  const c = (kind && COPY[kind]) || DEFAULT_COPY;
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
  kinds?: (Provenance | string)[];
}) {
  return (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-2 text-xs text-muted-foreground">
      {kinds.map((k) => {
        const c = (k && COPY[k]) || DEFAULT_COPY;
        return (
          <span key={k} className="flex items-center gap-2">
            <ProvenanceTag kind={k} />
            {c.hint}
          </span>
        );
      })}
    </div>
  );
}
