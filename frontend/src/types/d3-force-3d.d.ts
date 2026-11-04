/**
 * Minimal type declarations for d3-force-3d.
 * The package has no DefinitelyTyped entry; only the APIs we use are declared.
 */
declare module 'd3-force-3d' {
    import type {
        ForceCenter,
        ForceLink,
        ForceManyBody,
        ForceX,
        ForceY,
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

    export function forceX<N extends ForceNode3D>(x?: number): ForceX<N>;
    export function forceY<N extends ForceNode3D>(y?: number): ForceY<N>;
    export function forceZ(z?: number): {
        strength(): number;
        strength(strength: number): typeof forceZ;
    };
}
