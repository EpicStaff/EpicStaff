declare module 'd3-force-3d' {
    import { SimulationLinkDatum, SimulationNodeDatum } from 'd3-force';

    interface ForceNode3D extends SimulationNodeDatum {
        z?: number;
        vz?: number;
        fz?: number | null;
    }

    interface Simulation<N extends ForceNode3D> {
        force(name: string, force?: unknown): this;
        on(event: string, listener: () => void): this;
        alpha(value: number): this;
        restart(): this;
        stop(): this;
        tick(iterations?: number): this;
        nodes(): N[];
        nodes(nodes: N[]): this;
    }

    export function forceSimulation<N extends ForceNode3D>(nodes?: N[], numDimensions?: number): Simulation<N>;

    export function forceLink<N extends ForceNode3D>(
        links?: SimulationLinkDatum<N>[]
    ): { distance(d: number): unknown; strength(s: number): unknown };

    export function forceManyBody(): {
        strength(s: number): unknown;
        distanceMin(d: number): unknown;
        distanceMax(d: number): unknown;
    };

    export function forceCenter(x?: number, y?: number, z?: number): unknown;
}
