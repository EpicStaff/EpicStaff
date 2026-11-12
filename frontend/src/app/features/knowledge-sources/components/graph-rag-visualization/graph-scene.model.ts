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
    x: number;
    y: number;
    z: number;
    color: ColorTuple;
    radius: number;
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
    enabled: boolean;
    enableRotate: boolean;
    enablePan: boolean;
    enableZoom: boolean;
    screenSpacePanning: boolean;
    zoomToCursor: boolean;
    target: { x: number; y: number; z: number };
    mouseButtons: { LEFT: number; MIDDLE: number; RIGHT: number };
}
