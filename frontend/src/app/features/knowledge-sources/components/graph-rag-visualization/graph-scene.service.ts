import { Injectable } from '@angular/core';

import { VisualizationEntity, VisualizationRelationship } from '../../models/graph-visualization.model';

/** RGB tuple [0..1, 0..1, 0..1]. */
type ColorTuple = [number, number, number];

/** Stable color palette for entity types — deterministic hash maps each type to a hue. */
const TYPE_COLORS: string[] = [
    '#42a5f5', // blue
    '#66bb6a', // green
    '#ffa726', // orange
    '#ab47bc', // purple
    '#ef5350', // red
    '#26a69a', // teal
    '#ffee58', // yellow
    '#ec407a', // pink
    '#5c6bc0', // indigo
    '#8d6e63', // brown
    '#78909c', // blue-grey
    '#9ccc65', // light green
];

const HIGHLIGHT_COLOR: ColorTuple = [1.0, 0.95, 0.2]; // yellow highlight
const DIMMED_ALPHA = 0.15;
const LABEL_FONT_SIZE = 24;
const LABEL_CANVAS_HEIGHT = 36;

/** Computes a stable index from a string — used for type-to-color mapping. */
function stableHash(value: string): number {
    let hash = 0;
    for (let i = 0; i < value.length; i++) {
        hash = (hash << 5) - hash + value.charCodeAt(i);
        hash |= 0;
    }
    return Math.abs(hash);
}

/** Hex string to [r,g,b] in 0..1 range. */
function hexToRgb(hex: string): ColorTuple {
    const num = parseInt(hex.slice(1), 16);
    return [(num >> 16) / 255, ((num >> 8) & 0xff) / 255, (num & 0xff) / 255];
}

export interface GraphNode {
    index: number;
    title: string;
    type: string | null;
    description: string | null;
    degree: number;
    communityIds: string[];
    x: number;
    y: number;
    z: number;
    color: ColorTuple;
    radius: number;
}

export interface GraphEdge {
    sourceIndex: number;
    targetIndex: number;
    description: string | null;
    weight: number;
}

// Type-only imports — these do not pull Three.js into the runtime bundle.
import type {
    Camera,
    InstancedMesh,
    LineSegments,
    Material,
    OrthographicCamera,
    PerspectiveCamera,
    Raycaster,
    Scene,
    Sprite,
    WebGLRenderer,
} from 'three';

export interface SceneResources {
    renderer: WebGLRenderer;
    scene: Scene;
    camera: Camera;
    controls: OrbitControlsLike;
    nodesMesh: InstancedMesh;
    edgesLine: LineSegments;
    labelSprites: Sprite[];
    raycaster: Raycaster;
}

interface OrbitControlsLike {
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

@Injectable()
export class GraphSceneService {
    private three: typeof import('three') | null = null;
    private orbitControlsModule: { OrbitControls: new (...args: unknown[]) => OrbitControlsLike } | null = null;

    private resources: SceneResources | null = null;
    private animationFrameId: number | null = null;
    private resizeObserver: ResizeObserver | null = null;

    private nodes: GraphNode[] = [];
    private edges: GraphEdge[] = [];
    private titleToIndex = new Map<string, number>();
    private is3D = false;
    private labelsVisible = false;

    private highlightedIndices: Set<number> | null = null;
    private searchHighlightIndices: Set<number> | null = null;
    private visibleTypeSet: Set<string | null> | null = null;
    private hoveredNodeIndex: number | null = null;
    private connectedEdgeIndices: Set<number> = new Set();
    private wheelHandler: ((event: WheelEvent) => void) | null = null;

    /** Lazy-load Three.js and OrbitControls. */
    async loadDependencies(): Promise<void> {
        if (this.three) return;
        const [three, orbitModule] = await Promise.all([
            import('three'),
            import('three/addons/controls/OrbitControls.js'),
        ]);
        this.three = three;
        this.orbitControlsModule = orbitModule as unknown as {
            OrbitControls: new (...args: unknown[]) => OrbitControlsLike;
        };
    }

    /** Parse raw API data into internal node/edge arrays. */
    buildGraph(entities: VisualizationEntity[], relationships: VisualizationRelationship[]): void {
        this.titleToIndex.clear();
        this.nodes = entities.map((entity, index) => {
            this.titleToIndex.set(entity.title, index);
            const colorHex = entity.type ? TYPE_COLORS[stableHash(entity.type) % TYPE_COLORS.length] : TYPE_COLORS[0];
            const minRadius = 4;
            const maxRadius = 16;
            const maxDegree = Math.max(1, ...entities.map((e) => e.degree));
            const radius = minRadius + (entity.degree / maxDegree) * (maxRadius - minRadius);

            return {
                index,
                title: entity.title,
                type: entity.type,
                description: entity.description,
                degree: entity.degree,
                communityIds: entity.community_ids,
                x: (Math.random() - 0.5) * 200,
                y: (Math.random() - 0.5) * 200,
                z: 0,
                color: hexToRgb(colorHex),
                radius,
            };
        });

        this.edges = [];
        for (const relationship of relationships) {
            const sourceIndex = this.titleToIndex.get(relationship.source);
            const targetIndex = this.titleToIndex.get(relationship.target);
            if (sourceIndex !== undefined && targetIndex !== undefined) {
                this.edges.push({
                    sourceIndex,
                    targetIndex,
                    description: relationship.description,
                    weight: relationship.weight,
                });
            }
        }
    }

    getNodes(): GraphNode[] {
        return this.nodes;
    }

    getEdges(): GraphEdge[] {
        return this.edges;
    }

    /** Initialize the Three.js scene, renderer, and meshes. */
    initScene(canvas: HTMLCanvasElement, container: HTMLElement, is3D: boolean): SceneResources {
        const THREE = this.three!;
        this.is3D = is3D;

        // Renderer
        const renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true });
        renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
        renderer.setSize(container.clientWidth, container.clientHeight);

        // Scene
        const scene = new THREE.Scene();
        scene.background = new THREE.Color(0x1a1a1e);

        // Camera
        const camera = this.createCamera(container, is3D);

        // Controls
        const controls = new this.orbitControlsModule!.OrbitControls(camera, renderer.domElement) as OrbitControlsLike;
        controls.enableRotate = is3D;
        controls.screenSpacePanning = true;
        // LEFT=ROTATE (disabled in 2D, free for node drag), MIDDLE=PAN, RIGHT=PAN
        controls.mouseButtons = { LEFT: THREE.MOUSE.ROTATE, MIDDLE: THREE.MOUSE.PAN, RIGHT: THREE.MOUSE.PAN };
        if (is3D) {
            // Disable built-in zoom (slows with distance); use constant-speed dolly instead
            controls.enableZoom = false;
            this.setupConstantDolly(canvas, camera, controls);
        } else {
            controls.zoomToCursor = true;
        }

        // Nodes (InstancedMesh)
        const geometry = new THREE.SphereGeometry(1, 16, 12);
        const material = new THREE.MeshBasicMaterial({ color: 0xffffff });
        const nodesMesh = new THREE.InstancedMesh(geometry, material, Math.max(this.nodes.length, 1));
        nodesMesh.instanceMatrix.setUsage(THREE.DynamicDrawUsage);

        scene.add(nodesMesh);

        // Edges (LineSegments) with per-vertex colors for hover highlighting
        const edgePositions = new Float32Array(this.edges.length * 6);
        const edgeColors = new Float32Array(this.edges.length * 6);
        const edgeGeometry = new THREE.BufferGeometry();
        edgeGeometry.setAttribute('position', new THREE.Float32BufferAttribute(edgePositions, 3));
        edgeGeometry.setAttribute('color', new THREE.Float32BufferAttribute(edgeColors, 3));
        edgeGeometry.setDrawRange(0, this.edges.length * 2);
        const edgeMaterial = new THREE.LineBasicMaterial({
            vertexColors: true,
            transparent: true,
            opacity: 0.6,
        });
        const edgesLine = new THREE.LineSegments(edgeGeometry, edgeMaterial);
        edgesLine.frustumCulled = false;
        scene.add(edgesLine);

        // Labels
        const labelSprites: Sprite[] = [];

        // Raycaster
        const raycaster = new THREE.Raycaster();

        this.resources = { renderer, scene, camera, controls, nodesMesh, edgesLine, labelSprites, raycaster };

        // Initial instance transforms and colors
        this.updateInstanceMatrices();
        this.updateInstanceColors();
        this.updateEdgePositions();

        // Resize observer
        this.resizeObserver = new ResizeObserver(() => this.handleResize(container));
        this.resizeObserver.observe(container);

        // Start render loop
        this.startRenderLoop();

        return this.resources;
    }

    /** Switch between 2D and 3D. Recreates camera and adjusts controls. */
    switchDimension(container: HTMLElement, is3D: boolean): void {
        if (!this.resources) return;
        this.is3D = is3D;

        // Replace camera
        const newCamera = this.createCamera(container, is3D);
        this.resources.camera = newCamera;

        // Replace controls
        this.resources.controls.dispose();
        this.removeConstantDolly();
        const THREE = this.three!;
        const controls = new this.orbitControlsModule!.OrbitControls(
            newCamera,
            this.resources.renderer.domElement
        ) as OrbitControlsLike;
        controls.enableRotate = is3D;
        controls.screenSpacePanning = true;
        controls.mouseButtons = { LEFT: THREE.MOUSE.ROTATE, MIDDLE: THREE.MOUSE.PAN, RIGHT: THREE.MOUSE.PAN };
        if (is3D) {
            controls.enableZoom = false;
            this.setupConstantDolly(this.resources.renderer.domElement, newCamera, controls);
        } else {
            controls.zoomToCursor = true;
        }
        this.resources.controls = controls;

        // Reset z for 2D
        if (!is3D) {
            for (const node of this.nodes) {
                node.z = 0;
            }
        }
    }

    /** Update node positions from simulation data. Call this in the simulation tick. */
    updateNodePositions(positions: Array<{ x: number; y: number; z?: number }>): void {
        for (let i = 0; i < this.nodes.length && i < positions.length; i++) {
            this.nodes[i].x = positions[i].x ?? 0;
            this.nodes[i].y = positions[i].y ?? 0;
            this.nodes[i].z = this.is3D ? (positions[i].z ?? 0) : 0;
        }
        this.updateInstanceMatrices();
        this.updateEdgePositions();
        if (this.labelsVisible) {
            this.updateLabelPositions();
        }
    }

    /** Highlight specific node indices (community or search). Pass null to clear. */
    setHighlightedNodes(indices: Set<number> | null): void {
        this.highlightedIndices = indices;
        this.updateInstanceColors();
    }

    /** Search highlight — separate from community highlight. Pass null to clear. */
    setSearchHighlight(indices: Set<number> | null): void {
        this.searchHighlightIndices = indices;
        this.updateInstanceColors();
    }

    /** Filter by entity type. Pass null to show all. */
    setVisibleTypes(types: Set<string | null> | null): void {
        this.visibleTypeSet = types;
        this.updateInstanceMatrices();
        this.updateInstanceColors();
        this.updateEdgePositions();
    }

    /** Toggle labels on/off. */
    setLabelsVisible(visible: boolean): void {
        this.labelsVisible = visible;
        if (!this.resources) return;

        if (visible && this.resources.labelSprites.length === 0) {
            // Create label sprites
            for (const node of this.nodes) {
                const sprite = this.createLabelSprite(node.title);
                sprite.position.set(node.x, node.y + node.radius + 4, node.z);
                this.resources.scene.add(sprite);
                this.resources.labelSprites.push(sprite);
            }
        } else if (!visible) {
            for (const sprite of this.resources.labelSprites) {
                this.resources.scene.remove(sprite);
                sprite.material.map?.dispose();
                sprite.material.dispose();
            }
            this.resources.labelSprites = [];
        }
    }

    /** Raycast to find which node is under the given screen coordinates. Returns node index or -1. */
    pickNode(screenX: number, screenY: number, container: HTMLElement): number {
        if (!this.resources) return -1;
        const THREE = this.three!;

        const rect = container.getBoundingClientRect();
        const mouse = new THREE.Vector2(
            ((screenX - rect.left) / rect.width) * 2 - 1,
            -((screenY - rect.top) / rect.height) * 2 + 1
        );

        this.resources.raycaster.setFromCamera(mouse, this.resources.camera);
        const intersects = this.resources.raycaster.intersectObject(this.resources.nodesMesh);
        if (intersects.length > 0 && intersects[0].instanceId !== undefined) {
            return intersects[0].instanceId;
        }
        return -1;
    }

    /** Temporarily disable/enable OrbitControls entirely (used during node drag). */
    setControlsEnabled(enabled: boolean): void {
        if (!this.resources) return;
        this.resources.controls.enabled = enabled;
    }

    /** Returns the currently hovered node index, or null. */
    getHoveredNodeIndex(): number | null {
        return this.hoveredNodeIndex;
    }

    /** Project a node position to screen coordinates relative to the container. */
    projectToScreen(nodeIndex: number, container: HTMLElement): { x: number; y: number } | null {
        if (!this.resources || !this.three) return null;
        const node = this.nodes[nodeIndex];
        if (!node) return null;

        const THREE = this.three;
        const vector = new THREE.Vector3(node.x, node.y + node.radius + 2, node.z);
        vector.project(this.resources.camera);

        const rect = container.getBoundingClientRect();
        return {
            x: ((vector.x + 1) / 2) * rect.width,
            y: ((-vector.y + 1) / 2) * rect.height,
        };
    }

    /** Set which node is hovered — highlights connected edges and shows a title label. Pass null to clear. */
    setHoveredNode(nodeIndex: number | null): void {
        if (nodeIndex === this.hoveredNodeIndex) return;
        this.hoveredNodeIndex = nodeIndex;

        // Update connected edge set
        this.connectedEdgeIndices.clear();
        if (nodeIndex !== null) {
            for (let i = 0; i < this.edges.length; i++) {
                const edge = this.edges[i];
                if (edge.sourceIndex === nodeIndex || edge.targetIndex === nodeIndex) {
                    this.connectedEdgeIndices.add(i);
                }
            }
        }

        this.updateEdgeColors();
    }

    /** Convert screen coordinates to world position (projects onto z=0 plane for 2D, or camera plane for 3D). */
    screenToWorld(
        screenX: number,
        screenY: number,
        container: HTMLElement
    ): { x: number; y: number; z?: number } | null {
        if (!this.resources || !this.three) return null;
        const THREE = this.three;

        const rect = container.getBoundingClientRect();
        const mouse = new THREE.Vector2(
            ((screenX - rect.left) / rect.width) * 2 - 1,
            -((screenY - rect.top) / rect.height) * 2 + 1
        );

        this.resources.raycaster.setFromCamera(mouse, this.resources.camera);
        const ray = this.resources.raycaster.ray;

        // Intersect with z=0 plane
        const plane = new THREE.Plane(new THREE.Vector3(0, 0, 1), 0);
        const intersection = new THREE.Vector3();
        if (ray.intersectPlane(plane, intersection)) {
            return { x: intersection.x, y: intersection.y, z: intersection.z };
        }
        return null;
    }

    /** Dispose all Three.js resources. */
    dispose(): void {
        if (this.animationFrameId !== null) {
            cancelAnimationFrame(this.animationFrameId);
            this.animationFrameId = null;
        }

        this.resizeObserver?.disconnect();
        this.resizeObserver = null;
        this.removeConstantDolly();

        if (this.resources) {
            const { renderer, scene, nodesMesh, edgesLine, labelSprites, controls } = this.resources;

            controls.dispose();

            // Dispose labels
            for (const sprite of labelSprites) {
                sprite.material.map?.dispose();
                sprite.material.dispose();
                scene.remove(sprite);
            }

            // Dispose nodes
            nodesMesh.geometry.dispose();
            (nodesMesh.material as Material).dispose();
            scene.remove(nodesMesh);

            // Dispose edges
            edgesLine.geometry.dispose();
            (edgesLine.material as Material).dispose();
            scene.remove(edgesLine);

            // Dispose renderer
            renderer.dispose();
            renderer.forceContextLoss();

            this.resources = null;
        }

        this.nodes = [];
        this.edges = [];
        this.titleToIndex.clear();
    }

    /** Returns the color for a given entity type. */
    getTypeColor(type: string | null): string {
        if (!type) return TYPE_COLORS[0];
        return TYPE_COLORS[stableHash(type) % TYPE_COLORS.length];
    }

    // ---- private ----

    private setupConstantDolly(canvas: HTMLCanvasElement, camera: Camera, controls: OrbitControlsLike): void {
        const THREE = this.three!;
        const dollySpeed = 15;
        const raycaster = new THREE.Raycaster();
        const mouseNDC = new THREE.Vector2();

        this.wheelHandler = (event: WheelEvent) => {
            event.preventDefault();
            const sign = event.deltaY > 0 ? -1 : 1;

            // Compute ray direction towards cursor position
            const rect = canvas.getBoundingClientRect();
            mouseNDC.set(
                ((event.clientX - rect.left) / rect.width) * 2 - 1,
                -((event.clientY - rect.top) / rect.height) * 2 + 1
            );
            raycaster.setFromCamera(mouseNDC, camera);
            const direction = raycaster.ray.direction.clone().multiplyScalar(sign * dollySpeed);

            camera.position.x += direction.x;
            camera.position.y += direction.y;
            camera.position.z += direction.z;
            controls.target.x += direction.x;
            controls.target.y += direction.y;
            controls.target.z += direction.z;
        };
        canvas.addEventListener('wheel', this.wheelHandler, { passive: false });
    }

    private removeConstantDolly(): void {
        if (this.wheelHandler && this.resources) {
            this.resources.renderer.domElement.removeEventListener('wheel', this.wheelHandler);
            this.wheelHandler = null;
        }
    }

    private createCamera(container: HTMLElement, is3D: boolean): OrthographicCamera | PerspectiveCamera {
        const THREE = this.three!;
        const width = container.clientWidth || 1;
        const height = container.clientHeight || 1;

        if (is3D) {
            const camera = new THREE.PerspectiveCamera(60, width / height, 1, 5000);
            camera.position.set(0, 0, 300);
            return camera;
        } else {
            const halfW = width / 2;
            const halfH = height / 2;
            const camera = new THREE.OrthographicCamera(-halfW, halfW, halfH, -halfH, 1, 5000);
            camera.position.set(0, 0, 500);
            camera.lookAt(0, 0, 0);
            return camera;
        }
    }

    private isNodeVisible(node: GraphNode): boolean {
        if (this.visibleTypeSet && !this.visibleTypeSet.has(node.type)) {
            return false;
        }
        return true;
    }

    private updateInstanceMatrices(): void {
        if (!this.resources) return;
        const THREE = this.three!;
        const dummy = new THREE.Object3D();

        for (let i = 0; i < this.nodes.length; i++) {
            const node = this.nodes[i];
            if (this.isNodeVisible(node)) {
                dummy.position.set(node.x, node.y, node.z);
                dummy.scale.setScalar(node.radius);
            } else {
                // Move offscreen and scale to zero
                dummy.position.set(99999, 99999, 99999);
                dummy.scale.setScalar(0);
            }
            dummy.updateMatrix();
            this.resources.nodesMesh.setMatrixAt(i, dummy.matrix);
        }
        this.resources.nodesMesh.instanceMatrix.needsUpdate = true;
        this.resources.nodesMesh.computeBoundingSphere();
    }

    private updateInstanceColors(): void {
        if (!this.resources || !this.three) return;
        const THREE = this.three;
        const tempColor = new THREE.Color();

        for (let i = 0; i < this.nodes.length; i++) {
            const node = this.nodes[i];
            let color = node.color;

            if (this.searchHighlightIndices !== null) {
                if (this.searchHighlightIndices.has(i)) {
                    color = HIGHLIGHT_COLOR;
                } else {
                    color = [node.color[0] * DIMMED_ALPHA, node.color[1] * DIMMED_ALPHA, node.color[2] * DIMMED_ALPHA];
                }
            } else if (this.highlightedIndices !== null) {
                if (this.highlightedIndices.has(i)) {
                    color = HIGHLIGHT_COLOR;
                } else {
                    color = [node.color[0] * DIMMED_ALPHA, node.color[1] * DIMMED_ALPHA, node.color[2] * DIMMED_ALPHA];
                }
            }

            tempColor.setRGB(color[0], color[1], color[2]);
            this.resources.nodesMesh.setColorAt(i, tempColor);
        }
        this.resources.nodesMesh.instanceColor!.needsUpdate = true;
    }

    private updateEdgePositions(): void {
        if (!this.resources) return;
        const posAttr = this.resources.edgesLine.geometry.getAttribute('position');
        const positions = posAttr.array as Float32Array;

        let visibleCount = 0;
        for (const edge of this.edges) {
            const src = this.nodes[edge.sourceIndex];
            const tgt = this.nodes[edge.targetIndex];
            if (!this.isNodeVisible(src) || !this.isNodeVisible(tgt)) continue;

            const offset = visibleCount * 6;
            positions[offset] = src.x;
            positions[offset + 1] = src.y;
            positions[offset + 2] = src.z;
            positions[offset + 3] = tgt.x;
            positions[offset + 4] = tgt.y;
            positions[offset + 5] = tgt.z;
            visibleCount++;
        }

        this.resources.edgesLine.geometry.setDrawRange(0, visibleCount * 2);
        posAttr.needsUpdate = true;
        this.updateEdgeColors();
    }

    private updateLabelPositions(): void {
        if (!this.resources) return;
        for (let i = 0; i < this.resources.labelSprites.length && i < this.nodes.length; i++) {
            const node = this.nodes[i];
            const sprite = this.resources.labelSprites[i];
            sprite.position.set(node.x, node.y + node.radius + 4, node.z);
            sprite.visible = this.isNodeVisible(node);
        }
    }

    private createLabelSprite(text: string): Sprite {
        const THREE = this.three!;
        const font = `${LABEL_FONT_SIZE}px Inter, sans-serif`;

        // Measure text width first
        const measureCanvas = document.createElement('canvas');
        const measureCtx = measureCanvas.getContext('2d')!;
        measureCtx.font = font;
        const textWidth = measureCtx.measureText(text).width;

        const padding = 12;
        const canvasWidth = Math.ceil(textWidth + padding * 2);
        const canvasHeight = LABEL_CANVAS_HEIGHT;

        const canvas = document.createElement('canvas');
        canvas.width = canvasWidth;
        canvas.height = canvasHeight;
        const context = canvas.getContext('2d')!;

        // Background pill
        context.fillStyle = 'rgba(30, 30, 34, 0.85)';
        const radius = canvasHeight / 2;
        context.beginPath();
        context.roundRect(0, 0, canvasWidth, canvasHeight, radius);
        context.fill();

        // Text
        context.font = font;
        context.fillStyle = '#e8e8ec';
        context.textAlign = 'center';
        context.textBaseline = 'middle';
        context.fillText(text, canvasWidth / 2, canvasHeight / 2);

        const texture = new THREE.CanvasTexture(canvas);
        texture.needsUpdate = true;
        const material = new THREE.SpriteMaterial({ map: texture, transparent: true, depthTest: false });
        const sprite = new THREE.Sprite(material);
        // Scale proportional to canvas aspect ratio
        const spriteHeight = 8;
        const spriteWidth = spriteHeight * (canvasWidth / canvasHeight);
        sprite.scale.set(spriteWidth, spriteHeight, 1);
        return sprite;
    }

    private updateEdgeColors(): void {
        if (!this.resources) return;
        const colorAttr = this.resources.edgesLine.geometry.getAttribute('color');
        const colors = colorAttr.array as Float32Array;

        const defaultColor: ColorTuple = [0.5, 0.5, 0.55];
        const highlightColor: ColorTuple = [1.0, 0.95, 0.4];

        let visibleIndex = 0;
        for (let i = 0; i < this.edges.length; i++) {
            const edge = this.edges[i];
            const src = this.nodes[edge.sourceIndex];
            const tgt = this.nodes[edge.targetIndex];
            if (!this.isNodeVisible(src) || !this.isNodeVisible(tgt)) continue;

            const color: ColorTuple = this.connectedEdgeIndices.has(i) ? highlightColor : defaultColor;

            const offset = visibleIndex * 6;
            colors[offset] = color[0];
            colors[offset + 1] = color[1];
            colors[offset + 2] = color[2];
            colors[offset + 3] = color[0];
            colors[offset + 4] = color[1];
            colors[offset + 5] = color[2];
            visibleIndex++;
        }
        colorAttr.needsUpdate = true;
    }

    private handleResize(container: HTMLElement): void {
        if (!this.resources) return;
        const width = container.clientWidth;
        const height = container.clientHeight;

        this.resources.renderer.setSize(width, height);

        const camera = this.resources.camera;
        if ((camera as PerspectiveCamera).isPerspectiveCamera) {
            const perspCamera = camera as PerspectiveCamera;
            perspCamera.aspect = width / height;
            perspCamera.updateProjectionMatrix();
        } else {
            const orthoCamera = camera as OrthographicCamera;
            orthoCamera.left = -width / 2;
            orthoCamera.right = width / 2;
            orthoCamera.top = height / 2;
            orthoCamera.bottom = -height / 2;
            orthoCamera.updateProjectionMatrix();
        }
    }

    private startRenderLoop(): void {
        const render = (): void => {
            if (!this.resources) return;
            this.resources.controls.update();
            this.resources.renderer.render(this.resources.scene, this.resources.camera);
            this.animationFrameId = requestAnimationFrame(render);
        };
        this.animationFrameId = requestAnimationFrame(render);
    }
}
