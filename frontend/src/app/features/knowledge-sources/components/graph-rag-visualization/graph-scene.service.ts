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

/** Hover outline colors — adjust these three to change the look. */
const HOVERED_BORDER_COLOR: ColorTuple = [0.42, 0.45, 0.98]; // accent / indigo
const CONNECTED_BORDER_COLOR: ColorTuple = [0.3, 0.75, 0.55]; // teal-green
const HIGHLIGHT_EDGE_COLOR: ColorTuple = [1.0, 0.95, 0.4]; // bright yellow
const OUTLINE_SCALE = 1.35; // how much larger the outline ring is vs the node
const DOTS_PER_EDGE = 3;
const DOT_RADIUS = 1.5;
const DOT_SPEED = 0.4; // 0..1 per second

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
    id: string;
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
    private hoveredEdgeIndex: number | null = null;
    private connectedEdgeIndices: Set<number> = new Set();
    private connectedNodeIndices: Set<number> = new Set();
    private wheelHandler: ((event: WheelEvent) => void) | null = null;
    private outlineMesh: InstancedMesh | null = null;
    private highlightLinesObj: LineSegments | null = null;
    private dotsMesh: InstancedMesh | null = null;
    private dotsData: Array<{ edgeIndex: number; t: number; speed: number }> = [];

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
                id: entity.id,
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

        // Node outline mesh (BackSide rendering creates a border ring)
        const outlineGeometry = new THREE.SphereGeometry(1, 16, 12);
        const outlineMaterial = new THREE.MeshBasicMaterial({ side: THREE.BackSide });
        const outlineMesh = new THREE.InstancedMesh(outlineGeometry, outlineMaterial, Math.max(this.nodes.length, 1));
        outlineMesh.frustumCulled = false;
        scene.add(outlineMesh);
        this.outlineMesh = outlineMesh;

        // Highlight lines overlay (connected edges rendered brighter on top)
        const hlPositions = new Float32Array(this.edges.length * 6);
        const hlGeometry = new THREE.BufferGeometry();
        hlGeometry.setAttribute('position', new THREE.Float32BufferAttribute(hlPositions, 3));
        hlGeometry.setDrawRange(0, 0);
        const hlMaterial = new THREE.LineBasicMaterial({
            color: new THREE.Color(...HIGHLIGHT_EDGE_COLOR),
            transparent: true,
            opacity: 1.0,
            depthTest: false,
        });
        const highlightLines = new THREE.LineSegments(hlGeometry, hlMaterial);
        highlightLines.frustumCulled = false;
        highlightLines.renderOrder = 1;
        scene.add(highlightLines);
        this.highlightLinesObj = highlightLines;

        // Animated dots (small spheres that travel along highlighted edges)
        const maxDots = this.edges.length * DOTS_PER_EDGE;
        const dotGeometry = new THREE.SphereGeometry(1, 8, 6);
        const dotMaterial = new THREE.MeshBasicMaterial({ color: 0xffffff, depthTest: false });
        const dotsMesh = new THREE.InstancedMesh(dotGeometry, dotMaterial, Math.max(maxDots, 1));
        dotsMesh.frustumCulled = false;
        dotsMesh.renderOrder = 2;
        // Hide all dots initially
        const zeroDummy = new THREE.Object3D();
        zeroDummy.scale.setScalar(0);
        zeroDummy.position.set(99999, 99999, 99999);
        zeroDummy.updateMatrix();
        for (let i = 0; i < maxDots; i++) {
            dotsMesh.setMatrixAt(i, zeroDummy.matrix);
        }
        scene.add(dotsMesh);
        this.dotsMesh = dotsMesh;
        this.dotsData = [];

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
        if (this.hoveredNodeIndex !== null) {
            this.updateHoverVisuals();
        }
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

    /** Raycast to find which edge is nearest to the given screen coordinates. Returns edge index or -1. */
    pickEdge(screenX: number, screenY: number, container: HTMLElement, threshold = 6): number {
        if (!this.resources || !this.three) return -1;
        const THREE = this.three;
        const rect = container.getBoundingClientRect();
        const mx = screenX - rect.left;
        const my = screenY - rect.top;

        const tempVec = new THREE.Vector3();
        let bestIndex = -1;
        let bestDist = threshold;

        for (let i = 0; i < this.edges.length; i++) {
            const edge = this.edges[i];
            const src = this.nodes[edge.sourceIndex];
            const tgt = this.nodes[edge.targetIndex];
            if (!this.isNodeVisible(src) || !this.isNodeVisible(tgt)) continue;

            // Project both endpoints to screen
            tempVec.set(src.x, src.y, src.z);
            tempVec.project(this.resources.camera);
            const ax = ((tempVec.x + 1) / 2) * rect.width;
            const ay = ((-tempVec.y + 1) / 2) * rect.height;

            tempVec.set(tgt.x, tgt.y, tgt.z);
            tempVec.project(this.resources.camera);
            const bx = ((tempVec.x + 1) / 2) * rect.width;
            const by = ((-tempVec.y + 1) / 2) * rect.height;

            // Distance from point to line segment
            const dist = this.pointToSegmentDistance(mx, my, ax, ay, bx, by);
            if (dist < bestDist) {
                bestDist = dist;
                bestIndex = i;
            }
        }
        return bestIndex;
    }

    /** Set which edge is hovered — highlights connected nodes. Pass null to clear. */
    setHoveredEdge(edgeIndex: number | null): void {
        // If clearing edge hover while a node is hovered, don't touch dots or connected sets
        if (edgeIndex === null && this.hoveredNodeIndex !== null) {
            this.hoveredEdgeIndex = null;
            return;
        }

        // Clear any node hover first
        if (edgeIndex !== null && this.hoveredNodeIndex !== null) {
            this.hoveredNodeIndex = null; // bypass setHoveredNode to avoid clearing dots prematurely
        }

        if (edgeIndex === this.hoveredEdgeIndex) return;

        this.hoveredEdgeIndex = edgeIndex;
        this.connectedEdgeIndices.clear();
        this.connectedNodeIndices.clear();

        if (edgeIndex !== null) {
            const edge = this.edges[edgeIndex];
            this.connectedEdgeIndices.add(edgeIndex);
            this.connectedNodeIndices.add(edge.sourceIndex);
            this.connectedNodeIndices.add(edge.targetIndex);
            this.setupDots();
        } else {
            this.clearDots();
        }

        this.updateEdgeColors();
        this.updateHoverVisuals();
    }

    /** Returns the currently hovered edge index, or null. */
    getHoveredEdgeIndex(): number | null {
        return this.hoveredEdgeIndex;
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

    /** Set which node is hovered — highlights connected edges/nodes and shows outline. Pass null to clear. */
    setHoveredNode(nodeIndex: number | null): void {
        if (nodeIndex === this.hoveredNodeIndex) return;
        this.hoveredNodeIndex = nodeIndex;
        this.hoveredEdgeIndex = null;

        // Update connected edge and node sets
        this.connectedEdgeIndices.clear();
        this.connectedNodeIndices.clear();
        if (nodeIndex !== null) {
            for (let i = 0; i < this.edges.length; i++) {
                const edge = this.edges[i];
                if (edge.sourceIndex === nodeIndex) {
                    this.connectedEdgeIndices.add(i);
                    this.connectedNodeIndices.add(edge.targetIndex);
                } else if (edge.targetIndex === nodeIndex) {
                    this.connectedEdgeIndices.add(i);
                    this.connectedNodeIndices.add(edge.sourceIndex);
                }
            }
        }

        this.updateEdgeColors();
        this.updateHoverVisuals();
        if (nodeIndex !== null) {
            this.setupDots();
        } else {
            this.clearDots();
        }
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

            // Dispose outline mesh
            if (this.outlineMesh) {
                this.outlineMesh.geometry.dispose();
                (this.outlineMesh.material as Material).dispose();
                scene.remove(this.outlineMesh);
                this.outlineMesh = null;
            }

            // Dispose highlight lines
            if (this.highlightLinesObj) {
                this.highlightLinesObj.geometry.dispose();
                (this.highlightLinesObj.material as Material).dispose();
                scene.remove(this.highlightLinesObj);
                this.highlightLinesObj = null;
            }

            // Dispose dots
            if (this.dotsMesh) {
                this.dotsMesh.geometry.dispose();
                (this.dotsMesh.material as Material).dispose();
                scene.remove(this.dotsMesh);
                this.dotsMesh = null;
                this.dotsData = [];
            }

            // Dispose renderer
            renderer.dispose();
            renderer.forceContextLoss();

            this.resources = null;
        }

        this.hoveredNodeIndex = null;
        this.hoveredEdgeIndex = null;
        this.connectedEdgeIndices.clear();
        this.connectedNodeIndices.clear();
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
        if (this.resources.nodesMesh.instanceColor) {
            this.resources.nodesMesh.instanceColor.needsUpdate = true;
        }
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

    private updateHoverVisuals(): void {
        if (!this.resources || !this.three) return;
        const THREE = this.three;
        const dummy = new THREE.Object3D();
        const tempColor = new THREE.Color();

        // --- Outline mesh ---
        if (this.outlineMesh) {
            for (let i = 0; i < this.nodes.length; i++) {
                const node = this.nodes[i];
                let borderColor: ColorTuple | null = null;

                if (i === this.hoveredNodeIndex) {
                    borderColor = HOVERED_BORDER_COLOR;
                } else if (this.connectedNodeIndices.has(i)) {
                    borderColor = CONNECTED_BORDER_COLOR;
                }

                if (borderColor) {
                    dummy.position.set(node.x, node.y, node.z);
                    dummy.scale.setScalar(node.radius * OUTLINE_SCALE);
                    tempColor.setRGB(borderColor[0], borderColor[1], borderColor[2]);
                } else {
                    dummy.position.set(99999, 99999, 99999);
                    dummy.scale.setScalar(0);
                    tempColor.setRGB(0, 0, 0);
                }

                dummy.updateMatrix();
                this.outlineMesh.setMatrixAt(i, dummy.matrix);
                this.outlineMesh.setColorAt(i, tempColor);
            }
            this.outlineMesh.instanceMatrix.needsUpdate = true;
            if (this.outlineMesh.instanceColor) {
                this.outlineMesh.instanceColor.needsUpdate = true;
            }
        }

        // --- Highlight lines (connected edges rendered on top) ---
        if (this.highlightLinesObj) {
            const posAttr = this.highlightLinesObj.geometry.getAttribute('position');
            const positions = posAttr.array as Float32Array;
            let count = 0;

            if (this.connectedEdgeIndices.size > 0) {
                for (const edgeIdx of this.connectedEdgeIndices) {
                    const edge = this.edges[edgeIdx];
                    const src = this.nodes[edge.sourceIndex];
                    const tgt = this.nodes[edge.targetIndex];
                    const offset = count * 6;
                    positions[offset] = src.x;
                    positions[offset + 1] = src.y;
                    positions[offset + 2] = src.z;
                    positions[offset + 3] = tgt.x;
                    positions[offset + 4] = tgt.y;
                    positions[offset + 5] = tgt.z;
                    count++;
                }
            }

            this.highlightLinesObj.geometry.setDrawRange(0, count * 2);
            posAttr.needsUpdate = true;
        }
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

    /** Distance from point (px,py) to line segment (ax,ay)-(bx,by) in screen pixels. */
    private pointToSegmentDistance(px: number, py: number, ax: number, ay: number, bx: number, by: number): number {
        const dx = bx - ax;
        const dy = by - ay;
        const lenSq = dx * dx + dy * dy;
        if (lenSq === 0) return Math.hypot(px - ax, py - ay);
        let t = ((px - ax) * dx + (py - ay) * dy) / lenSq;
        t = Math.max(0, Math.min(1, t));
        return Math.hypot(px - (ax + t * dx), py - (ay + t * dy));
    }

    private setupDots(): void {
        this.dotsData = [];
        if (this.connectedEdgeIndices.size === 0) return;

        for (const edgeIdx of this.connectedEdgeIndices) {
            for (let d = 0; d < DOTS_PER_EDGE; d++) {
                this.dotsData.push({
                    edgeIndex: edgeIdx,
                    t: d / DOTS_PER_EDGE,
                    speed: DOT_SPEED,
                });
            }
        }
    }

    private updateDots(): void {
        if (!this.dotsMesh || !this.three || this.dotsData.length === 0) return;
        const THREE = this.three;
        const dummy = new THREE.Object3D();

        for (let i = 0; i < this.dotsData.length; i++) {
            const dot = this.dotsData[i];
            dot.t += dot.speed / 60; // ~60fps
            if (dot.t > 1) dot.t -= 1;

            const edge = this.edges[dot.edgeIndex];
            const src = this.nodes[edge.sourceIndex];
            const tgt = this.nodes[edge.targetIndex];
            const t = dot.t;

            dummy.position.set(src.x + (tgt.x - src.x) * t, src.y + (tgt.y - src.y) * t, src.z + (tgt.z - src.z) * t);
            dummy.scale.setScalar(DOT_RADIUS);
            dummy.updateMatrix();
            this.dotsMesh.setMatrixAt(i, dummy.matrix);
        }

        // Hide unused instances
        const zeroDummy = new THREE.Object3D();
        zeroDummy.scale.setScalar(0);
        zeroDummy.position.set(99999, 99999, 99999);
        zeroDummy.updateMatrix();
        const maxDots = this.edges.length * DOTS_PER_EDGE;
        for (let i = this.dotsData.length; i < maxDots; i++) {
            this.dotsMesh.setMatrixAt(i, zeroDummy.matrix);
        }
        this.dotsMesh.instanceMatrix.needsUpdate = true;
    }

    private clearDots(): void {
        if (!this.dotsMesh || !this.three) return;
        this.dotsData = [];
        const THREE = this.three;
        const zeroDummy = new THREE.Object3D();
        zeroDummy.scale.setScalar(0);
        zeroDummy.position.set(99999, 99999, 99999);
        zeroDummy.updateMatrix();
        const maxDots = this.edges.length * DOTS_PER_EDGE;
        for (let i = 0; i < maxDots; i++) {
            this.dotsMesh.setMatrixAt(i, zeroDummy.matrix);
        }
        this.dotsMesh.instanceMatrix.needsUpdate = true;
    }

    private startRenderLoop(): void {
        const render = (): void => {
            if (!this.resources) return;
            this.resources.controls.update();
            if (this.dotsData.length > 0) {
                this.updateDots();
            }
            this.resources.renderer.render(this.resources.scene, this.resources.camera);
            this.animationFrameId = requestAnimationFrame(render);
        };
        this.animationFrameId = requestAnimationFrame(render);
    }
}
