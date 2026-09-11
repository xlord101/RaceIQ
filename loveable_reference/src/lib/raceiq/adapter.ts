import { CIRCUIT_LIST, CIRCUITS, type CircuitId } from "./circuits";
import type { RaceIQAdapter } from "./contracts";
import { DRIVER_BY_CODE } from "./drivers";
import { recommend, simulateWhatIf } from "./engine";
import { raceDuration, snapshotAt } from "./sim";

/**
 * Placeholder adapter. It implements the same RaceIQAdapter contract a real
 * RaceIQ backend adapter will implement, so swapping data sources is a one-line
 * change at <RaceIQProvider adapter={...}> and touches no component.
 */
export const simulationAdapter: RaceIQAdapter = {
  id: "simulation",
  kind: "simulation",
  circuits: CIRCUIT_LIST,
  circuit: (circuitId) => CIRCUITS[circuitId as CircuitId],
  driver: (code) => DRIVER_BY_CODE[code],
  duration: (circuitId) => raceDuration(circuitId as CircuitId),
  snapshotAt: (circuitId, time) => snapshotAt(circuitId as CircuitId, time),
  recommend,
  whatIf: simulateWhatIf,
};
