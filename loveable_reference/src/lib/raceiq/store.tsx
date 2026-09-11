import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { simulationAdapter } from "./adapter";
import type {
  DriverIdentity,
  Posture,
  RaceIQAdapter,
  RaceIQCircuit,
  RaceIQDriverState,
  RaceIQRecommendation,
  RaceIQSnapshot,
  RaceIQWhatIfBranch,
} from "./contracts";

interface RaceIQContextValue {
  adapter: RaceIQAdapter;
  circuits: RaceIQCircuit[];
  circuit: RaceIQCircuit;
  circuitId: string;
  setCircuit: (id: string) => void;
  time: number;
  setTime: (t: number) => void;
  duration: number;
  playing: boolean;
  toggle: () => void;
  pause: () => void;
  snapshot: RaceIQSnapshot;
  selected: string;
  setSelected: (code: string) => void;
  rival: string;
  setRival: (code: string) => void;
  /** Contract accessors — components never reach into a data producer. */
  driver: (code: string) => DriverIdentity;
  stateOf: (code: string) => RaceIQDriverState | undefined;
  recommendationFor: (code: string) => RaceIQRecommendation | undefined;
  whatIf: (code: string, action: Posture) => RaceIQWhatIfBranch | undefined;
}

const RaceIQContext = createContext<RaceIQContextValue | null>(null);

export function RaceIQProvider({
  children,
  adapter = simulationAdapter,
}: {
  children: ReactNode;
  /** Swap this for a RaceIQ backend adapter — no component changes required. */
  adapter?: RaceIQAdapter;
}) {
  const firstCircuit = adapter.circuits[0]!;
  const [circuitId, setCircuitId] = useState<string>(firstCircuit.id);
  const [time, setTime] = useState(420);
  const [playing, setPlaying] = useState(false);
  const [selected, setSelected] = useState("OCO");
  const [rival, setRival] = useState("BEA");
  const raf = useRef<number | null>(null);

  const circuit = adapter.circuit(circuitId) ?? firstCircuit;
  const duration = adapter.duration(circuit.id);

  useEffect(() => {
    if (!playing) return;
    let last = performance.now();
    const step = (now: number) => {
      const dt = (now - last) / 1000;
      last = now;
      setTime((t) => {
        const next = t + dt;
        if (next >= duration) {
          setPlaying(false);
          return duration;
        }
        return next;
      });
      raf.current = requestAnimationFrame(step);
    };
    raf.current = requestAnimationFrame(step);
    return () => {
      if (raf.current) cancelAnimationFrame(raf.current);
    };
  }, [playing, duration]);

  const setCircuit = useCallback(
    (id: string) => {
      setCircuitId(id);
      setTime(Math.min(420, adapter.duration(id)));
    },
    [adapter],
  );

  const snapshot = useMemo(
    () => adapter.snapshotAt(circuit.id, time),
    [adapter, circuit.id, time],
  );

  const value: RaceIQContextValue = {
    adapter,
    circuits: adapter.circuits,
    circuit,
    circuitId: circuit.id,
    setCircuit,
    time,
    setTime,
    duration,
    playing,
    toggle: () => setPlaying((p) => !p),
    pause: () => setPlaying(false),
    snapshot,
    selected,
    setSelected: (code) => {
      setSelected((prev) => {
        if (code === prev) return prev;
        setRival((r) => (r === code ? prev : r));
        return code;
      });
    },
    rival,
    setRival,
    driver: (code) => adapter.driver(code) ?? { code },
    stateOf: (code) => snapshot.byCode[code],
    recommendationFor: (code) => adapter.recommend?.(snapshot, code),
    whatIf: (code, action) => adapter.whatIf?.(snapshot, code, action),
  };

  return <RaceIQContext.Provider value={value}>{children}</RaceIQContext.Provider>;
}

export function useRaceIQ() {
  const ctx = useContext(RaceIQContext);
  if (!ctx) throw new Error("useRaceIQ must be used inside RaceIQProvider");
  return ctx;
}
