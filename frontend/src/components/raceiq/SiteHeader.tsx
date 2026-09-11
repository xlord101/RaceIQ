import { Link } from "@tanstack/react-router";

const NAV = [
  { to: "/", label: "Live Race" },
  { to: "/what-if", label: "What If" },
  { to: "/why", label: "Why" },
  { to: "/impact", label: "Real-World Impact" },
] as const;

export function SiteHeader() {
  return (
    <header className="sticky top-0 z-20 border-b border-border bg-background/85 backdrop-blur">
      <div className="mx-auto grid max-w-[1600px] grid-cols-[minmax(0,1fr)_auto] items-center gap-4 px-4 py-3 sm:px-6">
        <Link to="/" className="data min-w-0 truncate text-sm font-semibold tracking-[0.18em]">
          RACE<span className="text-primary">IQ</span>
        </Link>
        <nav className="flex shrink-0 items-center gap-1 overflow-x-auto">
          {NAV.map((item) => (
            <Link
              key={item.to}
              to={item.to}
              activeOptions={{ exact: item.to === "/" }}
              activeProps={{ className: "bg-accent text-foreground" }}
              inactiveProps={{ className: "text-muted-foreground hover:bg-accent/50" }}
              className="rounded-lg px-2.5 py-1.5 text-xs transition-colors sm:text-sm"
            >
              {item.label}
            </Link>
          ))}
        </nav>
      </div>
    </header>
  );
}
