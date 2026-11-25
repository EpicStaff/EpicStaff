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
    ): {
        distance(distance: number): unknown;
        /** A constant, or an accessor called once per link with the link and its index in `links`. */
        strength(strength: number | ((link: ForceLink3D<N>, index: number) => number)): unknown;
    };

    interface ForceManyBody3D {
        strength(strength: number): ForceManyBody3D;
        distanceMin(distance: number): ForceManyBody3D;
        distanceMax(distance: number): ForceManyBody3D;
    }
    export function forceManyBody(): ForceManyBody3D;

    /** Keeps nodes apart: a constant radius, or an accessor called once per node with the node and its index. */
    export function forceCollide<N extends ForceNode3D>(
        radius?: number | ((node: N, index: number, nodes: N[]) => number)
    ): {
        strength(strength: number): unknown;
        iterations(iterations: number): unknown;
    };

    export function forceCenter(x?: number, y?: number, z?: number): unknown;

    interface ForceAxis3D {
        strength(strength: number): ForceAxis3D;
    }
    /** Per-axis spring pulling each node toward the target coordinate; strength 0..1, applied each tick. */
    export function forceX(x?: number): ForceAxis3D;
    export function forceY(y?: number): ForceAxis3D;
    export function forceZ(z?: number): ForceAxis3D;
}
