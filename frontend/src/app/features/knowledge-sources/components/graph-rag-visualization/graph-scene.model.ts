import type { Camera, InstancedMesh, Raycaster, Scene, Sprite, WebGLRenderer } from 'three';

/** RGB tuple [0..1, 0..1, 0..1]. */
export type ColorTuple = [number, number, number];

export interface GraphNode {
    id: string;
    index: number;
    title: string;
    type: string | null;
    description: string | null;
    degree: number;
    /** Top-level community the entity belongs to; null when it has none. */
    communityId: string | null;
    x: number;
    y: number;
    z: number;
    /** Color by entity type. */
    color: ColorTuple;
    /** Color by community, used while nodes are grouped by community. */
    communityColor: ColorTuple;
    radius: number;
}

/** A node as the force simulation sees it; `z`/`vz` stay unset in two dimensions. */
export interface ForceLayoutNode {
    x?: number;
    y?: number;
    z?: number;
    vx?: number;
    vy?: number;
    vz?: number;
}

export interface GraphEdge {
    id: string;
    sourceIndex: number;
    targetIndex: number;
    description: string | null;
    weight: number;
}

export interface SceneResources {
    renderer: WebGLRenderer;
    scene: Scene;
    camera: Camera;
    controls: OrbitControlsLike;
    nodesMesh: InstancedMesh;
    edgesMesh: InstancedMesh;
    labelSprites: Sprite[];
    raycaster: Raycaster;
}

export interface OrbitControlsLike {
    update(): void;
    dispose(): void;
    addEventListener(type: 'change', listener: () => void): void;
    removeEventListener(type: 'change', listener: () => void): void;
    enabled: boolean;
    enableRotate: boolean;
    enablePan: boolean;
    enableZoom: boolean;
    screenSpacePanning: boolean;
    zoomToCursor: boolean;
    target: { x: number; y: number; z: number };
    mouseButtons: { LEFT: number; MIDDLE: number; RIGHT: number };
}
