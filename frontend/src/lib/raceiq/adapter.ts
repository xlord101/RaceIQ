import { backendAdapter } from "./backend-adapter";
import { CIRCUIT_LIST, CIRCUITS, type CircuitId } from "./circuits";
import type { RaceIQAdapter } from "./contracts";
import { DRIVER_BY_CODE } from "./drivers";
import { recommend, simulateWhatIf } from "./engine";
import { raceDuration, snapshotAt } from "./sim";

export { backendAdapter };

/**
 * Fallback simulation adapter. It implements the same RaceIQAdapter contract
 * with honest SAMPLE provenance for emergency offline/demo fallback.
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

export const primaryAdapter: RaceIQAdapter = backendAdapter;

