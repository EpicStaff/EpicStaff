/**
 * Vendored d3-force-3d v3.0.6.
 * Only the APIs used by graph-rag-visualization are declared.
 */
import type {
    ForceCenter,
    ForceLink,
    ForceManyBody,
    Simulation,
    SimulationLinkDatum,
    SimulationNodeDatum,
} from 'd3-force';

export interface ForceNode3D extends SimulationNodeDatum {
    z?: number;
    vz?: number;
}

export function forceSimulation<N extends ForceNode3D>(nodes?: N[]): Simulation<N, SimulationLinkDatum<N>>;
export function forceLink<N extends ForceNode3D, L extends SimulationLinkDatum<N>>(links?: L[]): ForceLink<N, L>;
export function forceManyBody<N extends ForceNode3D>(): ForceManyBody<N>;
export function forceCenter<N extends ForceNode3D>(x?: number, y?: number, z?: number): ForceCenter<N>;
