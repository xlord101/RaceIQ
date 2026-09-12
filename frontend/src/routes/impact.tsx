import { createFileRoute } from "@tanstack/react-router";

export const Route = createFileRoute("/impact")({
  head: () => ({
    meta: [
      { title: "Real-World Impact — RaceIQ" },
      {
        name: "description",
        content:
          "RaceIQ demonstrates decision intelligence under continuously changing constraints: architecture, cross-domain transfer, and evaluation.",
      },
      { property: "og:title", content: "Real-World Impact — RaceIQ" },
      {
        name: "og:description",
        content:
          "How a pit-wall decision architecture transfers to energy-aware commercial logistics.",
      },
    ],
  }),
  component: Impact,
});

const PIPELINE = [
  {
    step: "OBSERVE",
    role: "Telemetry Ingestion",
    detail: "Public race timing, sector deltas, and speed telemetry streams.",
  },
  {
    step: "INFER",
    role: "State Estimation",
    detail: "Unobserved internal state (battery SoC, 8-state opponent HMM belief).",
  },
  {
    step: "SIMULATE",
    role: "Scenario Rollout",
    detail: "Tier-2 scenario-tree MPC evaluates candidate strategic postures.",
  },
  {
    step: "OPTIMIZE",
    role: "Constraint Bound",
    detail: "Regulated energy windows and deployment limits bound candidate moves.",
  },
  {
    step: "DECIDE",
    role: "Defensible Call",
    detail: "One clear expected-value recommendation: ATTACK, HOLD, DEFEND, or HARVEST.",
  },
];

const TRANSFER_MAPPING = [
  {
    race: "Race car battery SoC",
    logistics: "Vehicle battery State of Charge (SoC)",
  },
  {
    race: "Energy deployment",
    logistics: "Energy consumption & powertrain dispatch decision",
  },
  {
    race: "Opponent behaviour",
    logistics: "Dynamic traffic flow & route congestion conditions",
  },
  {
    race: "Gap / time margin",
    logistics: "Delivery SLA buffer & arrival time margin",
  },
  {
    race: "ATTACK / HOLD / DEFEND / HARVEST",
    logistics: "Operating strategies (Express, Nominal, Eco, Regenerate)",
  },
  {
    race: "Expected-value decision",
    logistics: "Cost vs. service-level reliability outcome",
  },
];

const LEARNING_POINTS = [
  {
    title: "1. Energy is a strategic resource.",
    desc: "It is not simply a quantity to maximize; preserving or deploying it fundamentally alters future operational options and recovery time.",
  },
  {
    title: "2. Opponent behaviour matters.",
    desc: "RaceIQ uses HMM belief states to estimate plausible hidden electrical states rather than assuming the opponent behaves deterministically.",
  },
  {
    title: "3. Uncertainty must be explicit.",
    desc: "Every data point in the pipeline is strictly classified along the provenance chain:",
    chain: "ACTUAL → INFERRED → MODEL OUTPUT → DECISION",
  },
  {
    title: "4. Prediction is not decision intelligence.",
    desc: "The valuable question is not merely “what will happen?” but “which available action has the highest expected value under the current constraints?”",
  },
];

const LIMITATIONS = [
  "Public data limits observability: vehicle SoC and rival electrical states are inferred through mathematical observers, not measured directly.",
  "Analytical approximations: closing speeds and straight-remaining distances use circuit geometry baselines where sub-sector timing is unmeasured.",
  "Prototype execution: What-If counterfactual branches are precomputed from frozen replay states during data preparation for reproducible evaluation.",
  "Regulatory scope: RaceIQ is regulation-aware, but is not a replacement for official FIA scrutineering and technical compliance validation.",
];

function Impact() {
  return (
    <main className="mx-auto max-w-[1000px] space-y-6 px-4 py-6 sm:px-6">
      {/* HEADER & CORE MESSAGE */}
      <header>
        <p className="eyebrow">Evaluation & Transferability</p>
        <h1 className="mt-1 text-xl font-semibold sm:text-2xl">Real-World Impact</h1>
        <div className="mt-3 rounded border border-border bg-surface p-4">
          <p className="font-mono text-xs uppercase tracking-widest text-primary">Core Message</p>
          <blockquote className="mt-1 text-base font-medium text-foreground sm:text-lg">
            “RaceIQ demonstrates decision intelligence under continuously changing constraints.”
          </blockquote>
        </div>
      </header>

      {/* ARCHITECTURE PIPELINE */}
      <section className="panel p-4">
        <p className="eyebrow">Decision Architecture</p>
        <div className="mt-3 flex flex-wrap items-center gap-1.5 font-mono text-xs font-semibold sm:gap-2">
          {PIPELINE.map((p, i) => (
            <div key={p.step} className="flex items-center gap-1.5 sm:gap-2">
              <span className="rounded border border-border bg-surface-raised px-2.5 py-1 text-foreground">
                {p.step}
              </span>
              {i < PIPELINE.length - 1 && (
                <span className="text-muted-foreground select-none">→</span>
              )}
            </div>
          ))}
        </div>

        <div className="mt-4 grid gap-2.5 sm:grid-cols-2 lg:grid-cols-5">
          {PIPELINE.map((p, i) => (
            <div
              key={p.step}
              className="rounded border border-border/70 bg-surface-raised/50 p-3"
            >
              <span className="data text-[10px] text-primary">0{i + 1}</span>
              <p className="mt-1 text-xs font-semibold text-foreground">{p.role}</p>
              <p className="mt-1 text-[11px] leading-snug text-muted-foreground">{p.detail}</p>
            </div>
          ))}
        </div>
      </section>

      {/* CROSS-DOMAIN TRANSFER */}
      <section className="panel p-4">
        <p className="eyebrow">Cross-Domain Transfer</p>
        <h2 className="mt-1 text-sm font-semibold text-foreground">
          Concrete Application: Energy-Aware Fleet & Logistics
        </h2>
        <div className="mt-3 rounded border border-primary/40 bg-primary/10 p-3">
          <p className="font-mono text-xs font-medium text-foreground">
            “RaceIQ does not transfer Formula 1 rules into logistics. It transfers the decision architecture.”
          </p>
        </div>

        <div className="mt-4 overflow-x-auto">
          <table className="w-full text-left text-xs">
            <thead>
              <tr className="border-b border-border text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
                <th className="py-2 pr-4">RaceIQ Concept</th>
                <th className="py-2 pl-4">Commercial Fleet & Logistics Equivalent</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border/50 font-mono">
              {TRANSFER_MAPPING.map((m) => (
                <tr key={m.race}>
                  <td className="py-2 pr-4 font-medium text-foreground">{m.race}</td>
                  <td className="py-2 pl-4 text-muted-foreground">{m.logistics}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      {/* PROTOTYPE VS PRODUCTION */}
      <section className="panel p-4">
        <p className="eyebrow">Observability & System Boundaries</p>
        <h2 className="mt-1 text-sm font-semibold text-foreground">
          Current Prototype vs. Production Specification
        </h2>
        <div className="mt-3 grid gap-3 md:grid-cols-2">
          <div className="rounded border border-border bg-surface-raised/40 p-3.5">
            <span className="data text-[10px] tracking-wider text-muted-foreground">
              CURRENT RESEARCH PROTOTYPE
            </span>
            <ul className="mt-2 space-y-1.5 text-xs text-muted-foreground">
              <li>• Consumes public race timing and speed telemetry feeds.</li>
              <li>• Infers unobserved state (SoC, opponent electrical intent) via observers.</li>
              <li>• Evaluates precomputed counterfactual branches from frozen replay states.</li>
              <li>• Zero private F1 telemetry or live production claims.</li>
            </ul>
          </div>

          <div className="rounded border border-border bg-surface-raised/40 p-3.5">
            <span className="data text-[10px] tracking-wider text-primary">
              PRODUCTION TELEMETRY SYSTEM
            </span>
            <ul className="mt-2 space-y-1.5 text-xs text-muted-foreground">
              <li>• Direct CAN-bus / telemetry sensor streams with high-frequency logging.</li>
              <li>• Direct battery cell voltage, MGU-K flux, and hydraulic brake pressure.</li>
              <li>• Continuous tyre carcass temperature, wear degradation, and fuel mass.</li>
              <li>• Live bi-directional dispatch and closed-loop actuation.</li>
            </ul>
          </div>
        </div>
      </section>

      {/* FINAL LEARNING & EVALUATION */}
      <section className="panel p-4">
        <p className="eyebrow">Judge-Facing Evaluation</p>
        <h2 className="mt-1 text-sm font-semibold text-foreground">
          Four Core Learning Principles
        </h2>
        <div className="mt-3 grid gap-3 sm:grid-cols-2">
          {LEARNING_POINTS.map((lp) => (
            <div
              key={lp.title}
              className="rounded border border-border/80 bg-surface-raised/60 p-3.5"
            >
              <h3 className="text-xs font-semibold text-foreground">{lp.title}</h3>
              <p className="mt-1 text-xs leading-relaxed text-muted-foreground">{lp.desc}</p>
              {lp.chain && (
                <div className="data mt-2 rounded border border-border/60 bg-surface px-2.5 py-1 text-[11px] font-semibold text-projected">
                  {lp.chain}
                </div>
              )}
            </div>
          ))}
        </div>
      </section>

      {/* LIMITATIONS */}
      <section className="panel p-4">
        <p className="eyebrow">Honest System Boundaries</p>
        <h2 className="mt-1 text-sm font-semibold text-foreground">System Limitations</h2>
        <ul className="mt-2.5 space-y-1.5 text-xs text-muted-foreground">
          {LIMITATIONS.map((lim, idx) => (
            <li key={idx} className="flex items-start gap-2">
              <span className="text-primary">•</span>
              <span>{lim}</span>
            </li>
          ))}
        </ul>
      </section>

      {/* CONCLUSION BANNER */}
      <footer className="rounded border border-primary/50 bg-surface p-4 text-center">
        <p className="font-mono text-sm font-semibold tracking-wide text-foreground sm:text-base">
          “The valuable output of a real-time system is not another prediction — it is a defensible decision.”
        </p>
      </footer>
    </main>
  );
}
