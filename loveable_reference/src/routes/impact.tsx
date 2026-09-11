import { createFileRoute } from "@tanstack/react-router";

export const Route = createFileRoute("/impact")({
  head: () => ({
    meta: [
      { title: "Real-World Impact — RaceIQ" },
      {
        name: "description",
        content:
          "The RaceIQ decision chain: data, state estimation, constraints, prediction, what-if, decision, measurable outcome.",
      },
      { property: "og:title", content: "Real-World Impact — RaceIQ" },
      {
        property: "og:description",
        content: "How a pit-wall decision architecture generalises to constrained decision-making.",
      },
    ],
  }),
  component: Impact,
});

const CHAIN = [
  { step: "Real-time data", detail: "Positions, gaps and timing arrive as a stream of measurements." },
  { step: "State estimation", detail: "Unmeasured quantities — stored energy, energy mode — are estimated with stated uncertainty." },
  { step: "Resource constraints", detail: "Regulated energy budgets and where Overtake Mode may be used bound every option." },
  { step: "Prediction", detail: "Probability of a successful move and its expected time value." },
  { step: "What-if simulation", detail: "Alternative decisions are branched from a frozen state, never over the record." },
  { step: "Decision", detail: "One clear call: attack, hold, defend or harvest." },
  { step: "Measurable outcome", detail: "Position and time change, so the call can be scored afterwards." },
];

function Impact() {
  return (
    <main className="mx-auto max-w-[1000px] px-4 py-6 sm:px-6">
      <h1 className="text-xl font-semibold sm:text-2xl">Real-world impact</h1>
      <p className="mt-1 max-w-2xl text-sm text-muted-foreground">
        Motorsport is the proof of concept, not the claim. RaceIQ is currently a race-replay decision
        interface — nothing here is deployed outside that context.
      </p>

      <ol className="mt-6 space-y-2">
        {CHAIN.map((c, i) => (
          <li key={c.step} className="panel grid grid-cols-[2rem_minmax(0,1fr)] gap-3 p-4">
            <span className="data text-sm text-primary">{String(i + 1).padStart(2, "0")}</span>
            <span className="min-w-0">
              <span className="data block text-sm tracking-[0.1em]">{c.step.toUpperCase()}</span>
              <span className="mt-1 block text-xs text-muted-foreground">{c.detail}</span>
            </span>
          </li>
        ))}
      </ol>

      <section className="panel mt-6 p-4">
        <h2 className="text-sm font-medium">The transferable part</h2>
        <p className="mt-2 text-xs text-muted-foreground">
          The pit wall is a hard version of a common problem: act now, with incomplete measurements,
          a limited resource, a competing party and a deadline. The architecture above does not
          depend on racing. Any setting with streaming data, unobserved internal state, a hard
          resource budget and a scoreable outcome can use the same chain — estimate the state, bound
          it by the constraint, predict, branch the alternatives, then commit to one decision and
          measure it.
        </p>
        <p className="mt-2 text-xs text-muted-foreground">
          What matters in that transfer is the discipline this interface enforces: measured,
          estimated and projected values are never mixed, and a projection is never presented as
          something that happened.
        </p>
      </section>
    </main>
  );
}
