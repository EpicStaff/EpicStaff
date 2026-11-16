declare module 'd3-force-3d' {
    /** Node fields the simulation reads and writes; `z`/`vz`/`fz` are used only with three dimensions. */
    interface ForceNode3D {
        index?: number;
        x?: number;
        y?: number;
        z?: number;
        vx?: number;
        vy?: number;
        vz?: number;
        fx?: number | null;
        fy?: number | null;
        fz?: number | null;
    }

    /** A link endpoint is a node object, or the node's index before the link force initialises it. */
    interface ForceLink3D<N extends ForceNode3D> {
        source: N | number | string;
        target: N | number | string;
        index?: number;
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
        links?: ForceLink3D<N>[]
    ): { distance(distance: number): unknown; strength(strength: number): unknown };

    export function forceManyBody(): {
        strength(strength: number): unknown;
        distanceMin(distance: number): unknown;
        distanceMax(distance: number): unknown;
    };

    export function forceCenter(x?: number, y?: number, z?: number): unknown;
}
