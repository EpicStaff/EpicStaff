import { Injectable } from '@angular/core';

import { VisualizationEntity, VisualizationRelationship } from '../../models/graph-visualization.model';

/** RGB tuple [0..1, 0..1, 0..1]. */
type ColorTuple = [number, number, number];

/** Stable color palette for entity types — high-saturation, high-contrast hues. */
const TYPE_COLORS: string[] = [
    '#2979ff', // vivid blue
    '#00e676', // vivid green
    '#ff9100', // vivid orange
    '#d500f9', // vivid purple
    '#ff1744', // vivid red
    '#1de9b6', // vivid teal
    '#ffea00', // vivid yellow
    '#f50057', // vivid pink
    '#3d5afe', // vivid indigo
    '#ff6d00', // vivid amber
    '#00e5ff', // vivid cyan
    '#76ff03', // vivid lime
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

/** Node opacity in 3D mode (0..1). Lower = more see-through between overlapping nodes. */
const NODE_3D_OPACITY = 0.75;

/** Edge opacity (0..1). Lower = more transparent connections. */
const EDGE_OPACITY = 0.6;

/** 3D edge width as a fraction of the smallest node's diameter. 0.1 = 1/10. */
const EDGE_3D_WIDTH_RATIO = 0.1;

/** 3D lighting intensities. Ambient lights all faces equally; directional creates the 3D gradient. */
const AMBIENT_LIGHT_INTENSITY = 0.4; // shadow-side base brightness
const DIRECTIONAL_LIGHT_INTENSITY = 1.6; // strong lit-vs-shadow contrast across the sphere

/**
 * 3D instance color multiplier — compensates for brightness lost to alpha blending
 * against the dark background. 1.0 = unmodified, 2.0 = 100 % brighter (GPU clamps to 1.0).
 */
const NODE_3D_BRIGHTNESS = 2.0;

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
    private depthNodesMesh: InstancedMesh | null = null;
    private edgesMesh3D: InstancedMesh | null = null;
    private edgeRadius3D = 1;
    private highlightLinesObj: LineSegments | null = null;
    private dotsMesh: InstancedMesh | null = null;
    private dotsData: Array<{ edgeIndex: number; t: number; speed: number }> = [];
    private sortedToOriginal: number[] = [];

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
        scene.background = new THREE.Color(0x000000);

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
        const nodeMaterial = is3D
            ? new THREE.MeshPhongMaterial({
                  color: 0xffffff,
                  transparent: true,
                  opacity: NODE_3D_OPACITY,
                  shininess: 40,
              })
            : new THREE.MeshBasicMaterial({ color: 0xffffff });
        const nodesMesh = new THREE.InstancedMesh(geometry, nodeMaterial, Math.max(this.nodes.length, 1));
        nodesMesh.instanceMatrix.setUsage(THREE.DynamicDrawUsage);

        // Lighting for 3D shading (gradient from center to edges)
        if (is3D) {
            const ambientLight = new THREE.AmbientLight(0xffffff, AMBIENT_LIGHT_INTENSITY);
            ambientLight.name = 'graphAmbient';
            scene.add(ambientLight);
            const dirLight = new THREE.DirectionalLight(0xffffff, DIRECTIONAL_LIGHT_INTENSITY);
            dirLight.name = 'graphDirectional';
            dirLight.position.set(0, 50, 100); // relative to camera — always lights from above-front
            camera.add(dirLight);
            scene.add(camera);
        }

        scene.add(nodesMesh);

        // Edges (LineSegments for 2D, InstancedMesh cylinders for 3D)
        const edgePositions = new Float32Array(this.edges.length * 6);
        const edgeColors = new Float32Array(this.edges.length * 6);
        const edgeGeometry = new THREE.BufferGeometry();
        edgeGeometry.setAttribute('position', new THREE.Float32BufferAttribute(edgePositions, 3));
        edgeGeometry.setAttribute('color', new THREE.Float32BufferAttribute(edgeColors, 3));
        edgeGeometry.setDrawRange(0, this.edges.length * 2);
        const edgeMaterial = new THREE.LineBasicMaterial({
            vertexColors: true,
            transparent: true,
            opacity: EDGE_OPACITY,
        });
        const edgesLine = new THREE.LineSegments(edgeGeometry, edgeMaterial);
        edgesLine.frustumCulled = false;
        if (!is3D) {
            scene.add(edgesLine);
        }

        // 3D cylinder edges
        if (is3D) {
            this.createEdgesMesh3D(scene);
        } else {
            this.edgesMesh3D = null;
        }

        // Node outline mesh (BackSide rendering creates a border ring)
        const outlineGeometry = new THREE.SphereGeometry(1, 16, 12);
        const outlineMaterial = new THREE.MeshBasicMaterial({ side: THREE.BackSide });
        const outlineMesh = new THREE.InstancedMesh(outlineGeometry, outlineMaterial, Math.max(this.nodes.length, 1));
        outlineMesh.frustumCulled = false;
        scene.add(outlineMesh);
        this.outlineMesh = outlineMesh;

        // Depth-only node proxy for 3D multi-pass edge occlusion
        if (is3D) {
            const depthMaterial = new THREE.MeshBasicMaterial({ colorWrite: false });
            const depthNodesMesh = new THREE.InstancedMesh(geometry, depthMaterial, Math.max(this.nodes.length, 1));
            depthNodesMesh.instanceMatrix = nodesMesh.instanceMatrix;
            depthNodesMesh.frustumCulled = false;
            depthNodesMesh.visible = false;
            scene.add(depthNodesMesh);
            this.depthNodesMesh = depthNodesMesh;
        } else {
            this.depthNodesMesh = null;
        }

        // Highlight lines overlay (connected edges rendered brighter)
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

        if (!is3D) {
            // 2D: nodes render on top of highlight lines
            nodesMesh.renderOrder = 2;
            outlineMesh.renderOrder = 2;
        }

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

        // Update node material for dimension
        const oldNodeMat = this.resources.nodesMesh.material as Material;
        const newNodeMat = is3D
            ? new THREE.MeshPhongMaterial({
                  color: 0xffffff,
                  transparent: true,
                  opacity: NODE_3D_OPACITY,
                  shininess: 40,
              })
            : new THREE.MeshBasicMaterial({ color: 0xffffff });
        this.resources.nodesMesh.material = newNodeMat;
        oldNodeMat.dispose();

        this.resources.nodesMesh.renderOrder = is3D ? 0 : 2;
        if (this.outlineMesh) {
            this.outlineMesh.renderOrder = is3D ? 0 : 2;
        }

        // Depth-only node proxy for 3D multi-pass edge occlusion
        if (is3D && !this.depthNodesMesh) {
            const depthMaterial = new THREE.MeshBasicMaterial({ colorWrite: false });
            const depthMesh = new THREE.InstancedMesh(
                this.resources.nodesMesh.geometry,
                depthMaterial,
                Math.max(this.nodes.length, 1)
            );
            depthMesh.instanceMatrix = this.resources.nodesMesh.instanceMatrix;
            depthMesh.frustumCulled = false;
            depthMesh.visible = false;
            this.resources.scene.add(depthMesh);
            this.depthNodesMesh = depthMesh;
        } else if (!is3D && this.depthNodesMesh) {
            (this.depthNodesMesh.material as Material).dispose();
            this.resources.scene.remove(this.depthNodesMesh);
            this.depthNodesMesh = null;
        }

        // 3D cylinder edges
        if (is3D && !this.edgesMesh3D) {
            this.resources.edgesLine.removeFromParent();
            this.createEdgesMesh3D(this.resources.scene);
        } else if (!is3D && this.edgesMesh3D) {
            (this.edgesMesh3D.material as Material).dispose();
            this.edgesMesh3D.geometry.dispose();
            this.resources.scene.remove(this.edgesMesh3D);
            this.edgesMesh3D = null;
            this.resources.scene.add(this.resources.edgesLine);
        }

        // Add/remove lights
        const existingAmbient = this.resources.scene.getObjectByName('graphAmbient');
        const existingDir = this.resources.camera.getObjectByName('graphDirectional');
        if (is3D && !existingAmbient) {
            const ambientLight = new THREE.AmbientLight(0xffffff, AMBIENT_LIGHT_INTENSITY);
            ambientLight.name = 'graphAmbient';
            this.resources.scene.add(ambientLight);
            const dirLight = new THREE.DirectionalLight(0xffffff, DIRECTIONAL_LIGHT_INTENSITY);
            dirLight.name = 'graphDirectional';
            dirLight.position.set(0, 50, 100);
            this.resources.camera.add(dirLight);
            this.resources.scene.add(this.resources.camera);
        } else if (!is3D) {
            if (existingAmbient) this.resources.scene.remove(existingAmbient);
            if (existingDir) {
                this.resources.camera.remove(existingDir);
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
            const instanceId = intersects[0].instanceId;
            // In 3D, instances are sorted by depth — remap slot to original node index
            if (this.is3D && this.sortedToOriginal.length > 0) {
                return this.sortedToOriginal[instanceId] ?? -1;
            }
            return instanceId;
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

            // Dispose depth-only node proxy (shares geometry + instanceMatrix with nodesMesh)
            if (this.depthNodesMesh) {
                (this.depthNodesMesh.material as Material).dispose();
                scene.remove(this.depthNodesMesh);
                this.depthNodesMesh = null;
            }

            // Dispose nodes
            nodesMesh.geometry.dispose();
            (nodesMesh.material as Material).dispose();
            scene.remove(nodesMesh);

            // Dispose edges
            edgesLine.geometry.dispose();
            (edgesLine.material as Material).dispose();
            scene.remove(edgesLine);

            if (this.edgesMesh3D) {
                this.edgesMesh3D.geometry.dispose();
                (this.edgesMesh3D.material as Material).dispose();
                scene.remove(this.edgesMesh3D);
                this.edgesMesh3D = null;
            }

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
        const bright = this.is3D ? NODE_3D_BRIGHTNESS : 1;

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

            tempColor.setRGB(color[0] * bright, color[1] * bright, color[2] * bright);
            this.resources.nodesMesh.setColorAt(i, tempColor);
        }
        if (this.resources.nodesMesh.instanceColor) {
            this.resources.nodesMesh.instanceColor.needsUpdate = true;
        }
    }

    private createEdgesMesh3D(scene: Scene): void {
        if (!this.three) return;
        const THREE = this.three;
        const minRadius = this.nodes.reduce((min, n) => Math.min(min, n.radius), Infinity);
        this.edgeRadius3D = minRadius * EDGE_3D_WIDTH_RATIO;
        const cylGeometry = new THREE.CylinderGeometry(1, 1, 1, 6);
        const cylMaterial = new THREE.MeshBasicMaterial({
            transparent: true,
            opacity: EDGE_OPACITY,
        });
        const edgesMesh = new THREE.InstancedMesh(cylGeometry, cylMaterial, Math.max(this.edges.length, 1));
        edgesMesh.instanceMatrix.setUsage(THREE.DynamicDrawUsage);
        edgesMesh.frustumCulled = false;
        scene.add(edgesMesh);
        this.edgesMesh3D = edgesMesh;
    }

    private updateEdgePositions(): void {
        if (!this.resources) return;

        if (this.is3D && this.edgesMesh3D && this.three) {
            this.updateEdgePositions3D();
        } else {
            this.updateEdgePositions2D();
        }
        this.updateEdgeColors();
    }

    private updateEdgePositions2D(): void {
        if (!this.resources) return;
        const posAttr = this.resources.edgesLine.geometry.getAttribute('position');
        const positions = posAttr.array as Float32Array;

        let visibleCount = 0;
        for (const edge of this.edges) {
            const src = this.nodes[edge.sourceIndex];
            const tgt = this.nodes[edge.targetIndex];
            if (!this.isNodeVisible(src) || !this.isNodeVisible(tgt)) continue;

            const dx = tgt.x - src.x;
            const dy = tgt.y - src.y;
            const dz = tgt.z - src.z;
            const len = Math.sqrt(dx * dx + dy * dy + dz * dz) || 1;
            const nx = dx / len;
            const ny = dy / len;
            const nz = dz / len;

            const offset = visibleCount * 6;
            positions[offset] = src.x + nx * src.radius;
            positions[offset + 1] = src.y + ny * src.radius;
            positions[offset + 2] = src.z + nz * src.radius;
            positions[offset + 3] = tgt.x - nx * tgt.radius;
            positions[offset + 4] = tgt.y - ny * tgt.radius;
            positions[offset + 5] = tgt.z - nz * tgt.radius;
            visibleCount++;
        }

        this.resources.edgesLine.geometry.setDrawRange(0, visibleCount * 2);
        posAttr.needsUpdate = true;
    }

    private updateEdgePositions3D(): void {
        if (!this.resources || !this.three || !this.edgesMesh3D) return;
        const THREE = this.three;
        const edgesMesh = this.edgesMesh3D;
        const dummy = new THREE.Object3D();
        const up = new THREE.Vector3(0, 1, 0);
        const dir = new THREE.Vector3();
        const quat = new THREE.Quaternion();
        const radius = this.edgeRadius3D;

        let visibleCount = 0;
        for (const edge of this.edges) {
            const src = this.nodes[edge.sourceIndex];
            const tgt = this.nodes[edge.targetIndex];
            if (!this.isNodeVisible(src) || !this.isNodeVisible(tgt)) {
                dummy.position.set(99999, 99999, 99999);
                dummy.scale.setScalar(0);
                dummy.updateMatrix();
                edgesMesh.setMatrixAt(visibleCount, dummy.matrix);
                visibleCount++;
                continue;
            }

            const dx = tgt.x - src.x;
            const dy = tgt.y - src.y;
            const dz = tgt.z - src.z;
            const len = Math.sqrt(dx * dx + dy * dy + dz * dz) || 1;
            const nx = dx / len;
            const ny = dy / len;
            const nz = dz / len;

            // Wall-to-wall endpoints
            const x0 = src.x + nx * src.radius;
            const y0 = src.y + ny * src.radius;
            const z0 = src.z + nz * src.radius;
            const x1 = tgt.x - nx * tgt.radius;
            const y1 = tgt.y - ny * tgt.radius;
            const z1 = tgt.z - nz * tgt.radius;
            const segLen = Math.sqrt((x1 - x0) ** 2 + (y1 - y0) ** 2 + (z1 - z0) ** 2);

            if (segLen < 0.01) {
                dummy.position.set(99999, 99999, 99999);
                dummy.scale.setScalar(0);
                dummy.updateMatrix();
                edgesMesh.setMatrixAt(visibleCount, dummy.matrix);
                visibleCount++;
                continue;
            }

            // Midpoint, orientation, scale
            dummy.position.set((x0 + x1) / 2, (y0 + y1) / 2, (z0 + z1) / 2);
            dir.set(nx, ny, nz);
            quat.setFromUnitVectors(up, dir);
            dummy.quaternion.copy(quat);
            dummy.scale.set(radius, segLen, radius);
            dummy.updateMatrix();
            edgesMesh.setMatrixAt(visibleCount, dummy.matrix);
            visibleCount++;
        }

        // Hide remaining slots
        dummy.position.set(99999, 99999, 99999);
        dummy.scale.setScalar(0);
        dummy.updateMatrix();
        for (let i = visibleCount; i < this.edges.length; i++) {
            edgesMesh.setMatrixAt(i, dummy.matrix);
        }

        edgesMesh.instanceMatrix.needsUpdate = true;
        edgesMesh.computeBoundingSphere();
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
                    const dx = tgt.x - src.x;
                    const dy = tgt.y - src.y;
                    const dz = tgt.z - src.z;
                    const len = Math.sqrt(dx * dx + dy * dy + dz * dz) || 1;
                    const nx = dx / len;
                    const ny = dy / len;
                    const nz = dz / len;
                    const offset = count * 6;
                    positions[offset] = src.x + nx * src.radius;
                    positions[offset + 1] = src.y + ny * src.radius;
                    positions[offset + 2] = src.z + nz * src.radius;
                    positions[offset + 3] = tgt.x - nx * tgt.radius;
                    positions[offset + 4] = tgt.y - ny * tgt.radius;
                    positions[offset + 5] = tgt.z - nz * tgt.radius;
                    count++;
                }
            }

            this.highlightLinesObj.geometry.setDrawRange(0, count * 2);
            posAttr.needsUpdate = true;
        }
    }

    private updateEdgeColors(): void {
        if (!this.resources) return;

        const defaultColor: ColorTuple = [0.5, 0.5, 0.55];
        const highlightColor: ColorTuple = [1.0, 0.95, 0.4];

        if (this.is3D && this.edgesMesh3D && this.three) {
            const tempColor = new this.three.Color();
            for (let i = 0; i < this.edges.length; i++) {
                const color: ColorTuple = this.connectedEdgeIndices.has(i) ? highlightColor : defaultColor;
                tempColor.setRGB(color[0], color[1], color[2]);
                this.edgesMesh3D.setColorAt(i, tempColor);
            }
            if (this.edgesMesh3D.instanceColor) {
                this.edgesMesh3D.instanceColor.needsUpdate = true;
            }
        } else {
            const colorAttr = this.resources.edgesLine.geometry.getAttribute('color');
            const colors = colorAttr.array as Float32Array;

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

            // Wall-to-wall endpoints (same offset as edges)
            const dx = tgt.x - src.x;
            const dy = tgt.y - src.y;
            const dz = tgt.z - src.z;
            const len = Math.sqrt(dx * dx + dy * dy + dz * dz) || 1;
            const nx = dx / len;
            const ny = dy / len;
            const nz = dz / len;
            const x0 = src.x + nx * src.radius;
            const y0 = src.y + ny * src.radius;
            const z0 = src.z + nz * src.radius;
            const x1 = tgt.x - nx * tgt.radius;
            const y1 = tgt.y - ny * tgt.radius;
            const z1 = tgt.z - nz * tgt.radius;
            const t = dot.t;

            dummy.position.set(x0 + (x1 - x0) * t, y0 + (y1 - y0) * t, z0 + (z1 - z0) * t);
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

    /** Sort node instances back-to-front relative to the camera for correct transparent blending. */
    private sortInstancesByDepth(): void {
        if (!this.resources || !this.three) return;
        const THREE = this.three;
        const camPos = this.resources.camera.position;
        const nodesMesh = this.resources.nodesMesh;
        const count = this.nodes.length;

        // Build squared-distance array and sort farthest-first (back-to-front)
        const order: Array<{ i: number; d: number }> = new Array(count);
        for (let i = 0; i < count; i++) {
            const node = this.nodes[i];
            if (this.isNodeVisible(node)) {
                const dx = node.x - camPos.x;
                const dy = node.y - camPos.y;
                const dz = node.z - camPos.z;
                order[i] = { i, d: dx * dx + dy * dy + dz * dz };
            } else {
                order[i] = { i, d: -1 };
            }
        }
        order.sort((a, b) => b.d - a.d);

        // Rewrite instance matrices and colors in sorted order
        const dummy = new THREE.Object3D();
        const tempColor = new THREE.Color();
        this.sortedToOriginal.length = count;

        for (let slot = 0; slot < count; slot++) {
            const nodeIndex = order[slot].i;
            this.sortedToOriginal[slot] = nodeIndex;
            const node = this.nodes[nodeIndex];

            if (this.isNodeVisible(node)) {
                dummy.position.set(node.x, node.y, node.z);
                dummy.scale.setScalar(node.radius);
            } else {
                dummy.position.set(99999, 99999, 99999);
                dummy.scale.setScalar(0);
            }
            dummy.updateMatrix();
            nodesMesh.setMatrixAt(slot, dummy.matrix);

            // Replicate color logic from updateInstanceColors
            let color: ColorTuple = node.color;
            if (this.searchHighlightIndices !== null) {
                color = this.searchHighlightIndices.has(nodeIndex)
                    ? HIGHLIGHT_COLOR
                    : [node.color[0] * DIMMED_ALPHA, node.color[1] * DIMMED_ALPHA, node.color[2] * DIMMED_ALPHA];
            } else if (this.highlightedIndices !== null) {
                color = this.highlightedIndices.has(nodeIndex)
                    ? HIGHLIGHT_COLOR
                    : [node.color[0] * DIMMED_ALPHA, node.color[1] * DIMMED_ALPHA, node.color[2] * DIMMED_ALPHA];
            }
            tempColor.setRGB(
                color[0] * NODE_3D_BRIGHTNESS,
                color[1] * NODE_3D_BRIGHTNESS,
                color[2] * NODE_3D_BRIGHTNESS
            );
            nodesMesh.setColorAt(slot, tempColor);
        }

        nodesMesh.instanceMatrix.needsUpdate = true;
        if (nodesMesh.instanceColor) {
            nodesMesh.instanceColor.needsUpdate = true;
        }
    }

    private startRenderLoop(): void {
        const render = (): void => {
            if (!this.resources) return;
            this.resources.controls.update();
            if (this.dotsData.length > 0) {
                this.updateDots();
            }
            if (this.is3D && this.depthNodesMesh) {
                this.render3DMultiPass();
            } else {
                this.resources.renderer.render(this.resources.scene, this.resources.camera);
            }
            this.animationFrameId = requestAnimationFrame(render);
        };
        this.animationFrameId = requestAnimationFrame(render);
    }

    /**
     * 3D multi-pass rendering: edges are occluded by nodes,
     * while nodes remain semi-transparent to each other.
     *
     * Pass 1 — depth-only node silhouettes write to depth buffer
     * Pass 2 — transparent nodes + outlines + labels (depthTest off, sorted back-to-front)
     * Pass 3 — edges + highlight lines + dots (depth-tested against Pass 1 — hidden behind nodes, on top in front)
     */
    private render3DMultiPass(): void {
        const { renderer, scene, camera, nodesMesh, labelSprites } = this.resources!;
        const depthMesh = this.depthNodesMesh!;
        const edgesMesh = this.edgesMesh3D;
        const nodeMat = nodesMesh.material as InstanceType<typeof import('three').MeshPhongMaterial>;

        const savedLabelVis = labelSprites.map((s) => s.visible);
        const savedBackground = scene.background;
        const prevAutoClear = renderer.autoClear;
        renderer.autoClear = false;
        renderer.clear();

        // Pass 1 — depth-only nodes (scene background is drawn here)
        nodesMesh.visible = false;
        if (edgesMesh) edgesMesh.visible = false;
        if (this.outlineMesh) this.outlineMesh.visible = false;
        if (this.highlightLinesObj) this.highlightLinesObj.visible = false;
        if (this.dotsMesh) this.dotsMesh.visible = false;
        for (const s of labelSprites) s.visible = false;
        depthMesh.visible = true;
        renderer.render(scene, camera);

        // Suppress background for subsequent passes to preserve color buffer
        scene.background = null;

        // Sort node instances back-to-front for correct transparent blending
        this.sortInstancesByDepth();

        // Pass 2 — transparent nodes + outlines + labels (skip depth test — occlusion handled by sorting)
        depthMesh.visible = false;
        nodeMat.depthTest = false;
        nodesMesh.visible = true;
        if (this.outlineMesh) this.outlineMesh.visible = true;
        labelSprites.forEach((s, i) => {
            s.visible = savedLabelVis[i];
        });
        renderer.render(scene, camera);
        nodeMat.depthTest = true;

        // Pass 3 — edges + decorations (depth-tested against node depth from Pass 1)
        nodesMesh.visible = false;
        if (this.outlineMesh) this.outlineMesh.visible = false;
        for (const s of labelSprites) s.visible = false;
        if (edgesMesh) edgesMesh.visible = true;
        if (this.highlightLinesObj) this.highlightLinesObj.visible = true;
        if (this.dotsMesh) this.dotsMesh.visible = true;
        renderer.render(scene, camera);

        scene.background = savedBackground;
        renderer.autoClear = prevAutoClear;
    }
}
