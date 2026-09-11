import oconPortrait from "@/assets/esteban-ocon-haas-2026.jpg.asset.json";
import bearmanPortrait from "@/assets/ollie-bearman-haas-2026.jpg.asset.json";

export interface Driver {
  code: string;
  name: string;
  team: string;
  /** Team colour token name defined in styles.css */
  color: string;
  tracked?: boolean;
  image?: string;
}

/** Reference grid used by the demo replay. Line-up only — no race results implied. */
export const DRIVERS: Driver[] = [
  { code: "VER", name: "M. Verstappen", team: "Red Bull", color: "#3671c6" },
  { code: "NOR", name: "L. Norris", team: "McLaren", color: "#ff8000" },
  { code: "PIA", name: "O. Piastri", team: "McLaren", color: "#ff8000" },
  { code: "LEC", name: "C. Leclerc", team: "Ferrari", color: "#e8002d" },
  { code: "HAM", name: "L. Hamilton", team: "Ferrari", color: "#e8002d" },
  { code: "RUS", name: "G. Russell", team: "Mercedes", color: "#27f4d2" },
  { code: "ANT", name: "K. Antonelli", team: "Mercedes", color: "#27f4d2" },
  {
    code: "OCO",
    name: "E. Ocon",
    team: "Haas",
    color: "#b6babd",
    tracked: true,
    image: oconPortrait.url,
  },
  {
    code: "BEA",
    name: "O. Bearman",
    team: "Haas",
    color: "#b6babd",
    tracked: true,
    image: bearmanPortrait.url,
  },
  { code: "ALO", name: "F. Alonso", team: "Aston Martin", color: "#229971" },
  { code: "STR", name: "L. Stroll", team: "Aston Martin", color: "#229971" },
  { code: "GAS", name: "P. Gasly", team: "Alpine", color: "#ff87bc" },
  { code: "COL", name: "F. Colapinto", team: "Alpine", color: "#ff87bc" },
  { code: "ALB", name: "A. Albon", team: "Williams", color: "#64c4ff" },
  { code: "SAI", name: "C. Sainz", team: "Williams", color: "#64c4ff" },
  { code: "TSU", name: "Y. Tsunoda", team: "Racing Bulls", color: "#6692ff" },
  { code: "HAD", name: "I. Hadjar", team: "Racing Bulls", color: "#6692ff" },
  { code: "HUL", name: "N. Hulkenberg", team: "Audi", color: "#00e701" },
  { code: "BOR", name: "G. Bortoleto", team: "Audi", color: "#00e701" },
  { code: "LAW", name: "L. Lawson", team: "Cadillac", color: "#c9a227" },
  { code: "PER", name: "S. Perez", team: "Cadillac", color: "#c9a227" },
  { code: "BOT", name: "V. Bottas", team: "Cadillac Res.", color: "#8c8f93" },
];

export const DRIVER_BY_CODE = Object.fromEntries(DRIVERS.map((d) => [d.code, d])) as Record<
  string,
  Driver
>;

export const HAAS_CODES = ["OCO", "BEA"] as const;

export function driverInfo(code: string): Driver {
  const d = DRIVER_BY_CODE[code];
  if (!d) throw new Error(`Unknown driver code: ${code}`);
  return d;
}
