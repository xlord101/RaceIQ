import { Link, useRouterState } from "@tanstack/react-router";

const NAV = [
  { to: "/", label: "Overview", exact: true },
  { to: "/live", label: "Live Race", exact: false },
  { to: "/what-if", label: "What If", exact: false },
  { to: "/why", label: "Why", exact: false },
  { to: "/impact", label: "Real-World Impact", exact: false },
] as const;

export function SiteHeader() {
  const routerState = useRouterState();
  const isPresentation = routerState.location.pathname === "/";

  // The landing presentation has its own immersive topbar and layout
  if (isPresentation) {
    return null;
  }

  return (
    <header className="sticky top-0 z-30 border-b border-border bg-[#050505]/90 backdrop-blur-md">
      <div className="mx-auto flex max-w-[1600px] items-center justify-between gap-4 px-4 py-2.5 sm:px-6">
        <div className="flex items-center gap-4">
          <Link to="/" className="data text-sm font-bold tracking-[0.18em] text-foreground transition-opacity hover:opacity-90">
            RACE<span className="text-primary">IQ</span>
          </Link>
          <span className="hidden text-border sm:inline">|</span>
          <span className="eyebrow hidden text-[10px] text-muted-foreground lg:inline">
            ENERGY &amp; OVERTAKE INTELLIGENCE
          </span>
        </div>

        <nav className="flex items-center gap-1 overflow-x-auto">
          {NAV.map((item) => (
            <Link
              key={item.to}
              to={item.to}
              activeOptions={{ exact: item.exact }}
              activeProps={{ className: "border border-border bg-surface-raised text-foreground font-medium" }}
              inactiveProps={{ className: "text-muted-foreground hover:text-foreground hover:bg-surface-raised/60" }}
              className="rounded px-2.5 py-1 text-xs transition-colors sm:text-sm"
            >
              {item.label}
            </Link>
          ))}
        </nav>

        <div className="hidden items-center gap-2 md:flex">
          <Link
            to="/"
            className="data inline-flex items-center gap-1.5 rounded border border-border bg-surface px-2.5 py-1 text-[11px] text-muted-foreground transition-colors hover:border-primary/50 hover:text-foreground"
          >
            <span>←</span>
            <span>Presentation</span>
          </Link>
        </div>
      </div>
    </header>
  );
}

