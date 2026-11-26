import { inject, Injectable, NgZone } from '@angular/core';
import type {
    Camera,
    InstancedMesh,
    Light,
    LineSegments,
    Material,
    OrthographicCamera,
    PerspectiveCamera,
    Scene,
    Sprite,
} from 'three';

import { VisualizationEntity, VisualizationRelationship } from '../../models/graph-visualization.model';
import {
    AMBIENT_LIGHT_INTENSITY,
    AMBIENT_LIGHT_NAME,
    BASE_RENDER_ORDER,
    CAMERA_FAR_PLANE,
    CAMERA_FIELD_OF_VIEW_DEGREES,
    CAMERA_NEAR_PLANE,
    DIMMED_ALPHA,
    DIRECTIONAL_LIGHT_INTENSITY,
    DIRECTIONAL_LIGHT_NAME,
    DIRECTIONAL_LIGHT_POSITION,
    DOLLY_SPEED,
    DOT_RADIUS,
    DOT_SPEED,
    DOT_SPHERE_HEIGHT_SEGMENTS,
    DOT_SPHERE_WIDTH_SEGMENTS,
    DOTS_PER_EDGE,
    EDGE_COLOR,
    EDGE_CYLINDER_RADIAL_SEGMENTS,
    EDGE_OPACITY,
    EDGE_OPACITY_3D,
    EDGE_PICK_THRESHOLD_PX,
    EDGE_WIDTH_RATIO,
    FOREGROUND_RENDER_ORDER,
    HIGHLIGHT_COLOR,
    HIGHLIGHT_EDGE_COLOR,
    HIGHLIGHT_LINE_FLOATS_PER_EDGE,
    HIGHLIGHT_LINES_RENDER_ORDER,
    HOVER_TOOLTIP_OFFSET_ABOVE_NODE,
    HOVERED_BORDER_COLOR,
    INITIAL_LAYOUT_SPREAD,
    LABEL_BACKGROUND_COLOR,
    LABEL_BORDER_COLOR,
    LABEL_BORDER_WIDTH,
    LABEL_CANVAS_HEIGHT,
    LABEL_FONT_FAMILY,
    LABEL_FONT_SIZE,
    LABEL_FONT_WEIGHT,
    LABEL_HORIZONTAL_PADDING,
    LABEL_MIN_NODE_PIXEL_RADIUS_2D,
    LABEL_MIN_NODE_PIXEL_RADIUS_3D,
    LABEL_OFFSET_ABOVE_NODE,
    LABEL_SCREEN_SIZE_SCALE_2D,
    LABEL_SIZE_INFLUENCE_2D,
    LABEL_SPRITE_HEIGHT,
    LABEL_TEXT_COLOR,
    MAX_FRAME_DELTA_SECONDS,
    MAX_PIXEL_RATIO,
    MIN_EDGE_SEGMENT_LENGTH,
    NODE_3D_BRIGHTNESS,
    NODE_3D_OPACITY,
    NODE_3D_SHININESS,
    NODE_MAX_RADIUS,
    NODE_MIN_RADIUS,
    NODE_SPHERE_HEIGHT_SEGMENTS,
    NODE_SPHERE_WIDTH_SEGMENTS,
    OFFSCREEN_POSITION,
    ORTHOGRAPHIC_CAMERA_DISTANCE,
    OUTLINE_SCALE,
    PERSPECTIVE_CAMERA_DISTANCE,
    SCENE_BACKGROUND,
    TYPE_COLORS,
} from './graph-scene.constants';
import { ColorTuple, GraphEdge, GraphNode, OrbitControlsLike, SceneResources } from './graph-scene.model';
import { getCommunityColor, hexToRgb, stableHash } from './graph-scene.utils';

@Injectable()
export class GraphSceneService {
    private readonly ngZone = inject(NgZone);
    private three: typeof import('three') | null = null;
    private orbitControlsModule: { OrbitControls: new (...args: unknown[]) => OrbitControlsLike } | null = null;

    private resources: SceneResources | null = null;
    private frameRequestId: number | null = null;
    private lastFrameTimestamp: number | null = null;
    /** Set when node positions, instance order or the camera changed since the last 3D depth sort. */
    private depthOrderStale = true;
    private resizeObserver: ResizeObserver | null = null;
    private readonly controlsChangeHandler = (): void => {
        this.depthOrderStale = true;
        // Nodes have not moved, but their distance to the camera (3D) or the ortho zoom (2D) has —
        // re-evaluate per-label distance culling. The call is cheap: a vector subtract + length per sprite.
        this.updateLabelPositions();
        this.requestRender();
    };

    private nodes: GraphNode[] = [];
    private edges: GraphEdge[] = [];
    private titleToIndex = new Map<string, number>();
    private is3D = false;
    /** When true, nodes are colored by community instead of by entity type. */
    private colorByCommunity = false;

    private highlightedIndices: Set<number> | null = null;
    private searchHighlightIndices: Set<number> | null = null;
    private searchVisibleIndices: Set<number> | null = null;
    private visibleTypeSet: Set<string | null> | null = null;
    private hoveredNodeIndex: number | null = null;
    private hoveredEdgeIndex: number | null = null;
    /** Node currently shown in the detail panel — keeps its border + a persistent label. */
    private selectedNodeIndex: number | null = null;
    /** Fires at the end of every rendered frame, so the component can reposition HTML overlays (e.g. selected-node label) during camera motion. */
    private afterRenderCallback: (() => void) | null = null;
    /** Nodes outlined while the user hovers a sidebar type-filter item. Null when no filter is hovered. */
    private typeHoverNodeIndices: Set<number> | null = null;
    private connectedEdgeIndices: Set<number> = new Set();
    private connectedNodeIndices: Set<number> = new Set();
    private wheelHandler: ((event: WheelEvent) => void) | null = null;
    private cameraAnimationFrameId: number | null = null;
    private outlineMesh: InstancedMesh | null = null;
    private depthNodesMesh: InstancedMesh | null = null;
    private edgeRadius = 1;
    private highlightLinesObj: LineSegments | null = null;
    private dotsMesh: InstancedMesh | null = null;
    private dotsData: Array<{ edgeIndex: number; t: number; speed: number }> = [];
    private sortedToOriginal: number[] = [];
    private instancesSorted = false;

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
        const maxDegree = Math.max(1, ...entities.map((e) => e.degree));
        this.nodes = entities.map((entity, index) => {
            this.titleToIndex.set(entity.title, index);
            const colorHex = entity.type ? TYPE_COLORS[stableHash(entity.type) % TYPE_COLORS.length] : TYPE_COLORS[0];
            const radius = NODE_MIN_RADIUS + (entity.degree / maxDegree) * (NODE_MAX_RADIUS - NODE_MIN_RADIUS);
            // Ordered by hierarchy level, so the first id is the top-level community.
            const communityId = entity.community_ids[0] ?? null;

            return {
                id: entity.id,
                index,
                title: entity.title,
                type: entity.type,
                description: null,
                degree: entity.degree,
                communityId,
                x: (Math.random() - 0.5) * INITIAL_LAYOUT_SPREAD,
                y: (Math.random() - 0.5) * INITIAL_LAYOUT_SPREAD,
                z: 0,
                color: hexToRgb(colorHex),
                communityColor: getCommunityColor(communityId),
                radius,
            };
        });

        this.edges = [];
        for (const relationship of relationships) {
            const sourceIndex = this.titleToIndex.get(relationship.source);
            const targetIndex = this.titleToIndex.get(relationship.target);
            if (sourceIndex !== undefined && targetIndex !== undefined) {
                this.edges.push({
                    id: relationship.id,
                    sourceIndex,
                    targetIndex,
                    description: null,
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

    /** True once `initScene` has created a renderer and until `dispose` runs. */
    isSceneInitialized(): boolean {
        return this.resources !== null;
    }

    /**
     * Initialize the Three.js renderer, camera, controls and graph meshes for a canvas.
     * Everything that schedules work (controls listeners, wheel listener, resize observer,
     * animation frames) is created outside the Angular zone, so an idle scene does not run
     * change detection; the scene renders only when something visible changed.
     */
    initScene(canvas: HTMLCanvasElement, container: HTMLElement, is3D: boolean): void {
        this.ngZone.runOutsideAngular(() => {
            const THREE = this.three!;
            this.is3D = is3D;

            const renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true });
            renderer.setPixelRatio(Math.min(window.devicePixelRatio, MAX_PIXEL_RATIO));
            renderer.setSize(container.clientWidth, container.clientHeight);

            const scene = new THREE.Scene();
            scene.background = new THREE.Color(SCENE_BACKGROUND);

            const camera = this.createCamera(container, is3D);
            const controls = this.createControls(camera, canvas, is3D);
            if (is3D) {
                this.addLights(scene, camera);
            }

            const { nodesMesh, edgesMesh } = this.createGraphMeshes(scene);
            const raycaster = new THREE.Raycaster();
            this.resources = { renderer, scene, camera, controls, nodesMesh, edgesMesh, labelSprites: [], raycaster };

            this.applyGraphState();

            this.resizeObserver = new ResizeObserver(() => this.handleResize(container));
            this.resizeObserver.observe(container);

            this.requestRender();
        });
    }

    /**
     * Rebuild the graph meshes from the current `buildGraph` data, keeping the renderer,
     * camera and controls — used when new data is loaded into an existing scene.
     */
    refreshGraph(): void {
        if (!this.resources) return;
        const scene = this.resources.scene;
        this.disposeGraphMeshes(scene);

        this.hoveredNodeIndex = null;
        this.hoveredEdgeIndex = null;
        this.selectedNodeIndex = null;
        this.connectedEdgeIndices.clear();
        this.connectedNodeIndices.clear();

        const { nodesMesh, edgesMesh } = this.createGraphMeshes(scene);
        this.resources.nodesMesh = nodesMesh;
        this.resources.edgesMesh = edgesMesh;
        this.applyGraphState();
        this.requestRender();
    }

    /** Switch between 2D and 3D. Recreates camera and adjusts controls. */
    switchDimension(container: HTMLElement, is3D: boolean): void {
        if (!this.resources) return;
        this.ngZone.runOutsideAngular(() => this.applyDimension(container, is3D));
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
        if (
            this.hoveredNodeIndex !== null ||
            this.selectedNodeIndex !== null ||
            this.typeHoverNodeIndices !== null ||
            this.connectedEdgeIndices.size > 0
        ) {
            this.updateHoverVisuals();
        }
        this.updateLabelPositions();
        this.requestRender();
    }

    /** Schedule a single frame; repeated calls before it runs are merged into one render. */
    requestRender(): void {
        if (!this.resources || this.frameRequestId !== null) return;
        this.frameRequestId = this.ngZone.runOutsideAngular(() =>
            requestAnimationFrame((timestamp) => this.renderFrame(timestamp))
        );
    }

    // ---- private: scene construction ----

    private createControls(camera: Camera, domElement: HTMLCanvasElement, is3D: boolean): OrbitControlsLike {
        const THREE = this.three!;
        const controls = new this.orbitControlsModule!.OrbitControls(camera, domElement) as OrbitControlsLike;
        controls.enableRotate = is3D;
        controls.screenSpacePanning = true;
        // LEFT=ROTATE (disabled in 2D, free for node drag), MIDDLE=PAN, RIGHT=PAN
        controls.mouseButtons = { LEFT: THREE.MOUSE.ROTATE, MIDDLE: THREE.MOUSE.PAN, RIGHT: THREE.MOUSE.PAN };
        if (is3D) {
            // Disable built-in zoom (slows with distance); use constant-speed dolly instead
            controls.enableZoom = false;
            this.setupConstantDolly(domElement, camera, controls);
        } else {
            controls.zoomToCursor = true;
        }
        controls.addEventListener('change', this.controlsChangeHandler);
        return controls;
    }

    private disposeControls(controls: OrbitControlsLike): void {
        controls.removeEventListener('change', this.controlsChangeHandler);
        controls.dispose();
        this.removeConstantDolly();
    }

    /** Lighting for 3D shading: ambient on the scene, directional attached to the camera so it follows it. */
    private addLights(scene: Scene, camera: Camera): void {
        const THREE = this.three!;
        const ambientLight = new THREE.AmbientLight(0xffffff, AMBIENT_LIGHT_INTENSITY);
        ambientLight.name = AMBIENT_LIGHT_NAME;
        scene.add(ambientLight);
        const directionalLight = new THREE.DirectionalLight(0xffffff, DIRECTIONAL_LIGHT_INTENSITY);
        directionalLight.name = DIRECTIONAL_LIGHT_NAME;
        directionalLight.position.set(...DIRECTIONAL_LIGHT_POSITION);
        camera.add(directionalLight);
        scene.add(camera);
    }

    /** Remove the 3D lights and detach `camera` (which carries the directional light) from the scene. */
    private removeLights(scene: Scene, camera: Camera): void {
        const ambientLight = scene.getObjectByName(AMBIENT_LIGHT_NAME) as Light | undefined;
        if (ambientLight) {
            scene.remove(ambientLight);
            ambientLight.dispose();
        }
        const directionalLight = camera.getObjectByName(DIRECTIONAL_LIGHT_NAME) as Light | undefined;
        if (directionalLight) {
            camera.remove(directionalLight);
            directionalLight.dispose();
        }
        scene.remove(camera);
    }

    private applyDimension(container: HTMLElement, is3D: boolean): void {
        const resources = this.resources!;
        this.is3D = is3D;

        // Look up the lights on the outgoing camera and detach it before it is replaced;
        // otherwise each 3D→2D→3D round trip leaves the old camera and its light in the scene.
        this.removeLights(resources.scene, resources.camera);
        this.disposeControls(resources.controls);

        const camera = this.createCamera(container, is3D);
        resources.camera = camera;
        resources.controls = this.createControls(camera, resources.renderer.domElement, is3D);
        if (is3D) {
            this.addLights(resources.scene, camera);
        }

        // Reset z for 2D
        if (!is3D) {
            for (const node of this.nodes) {
                node.z = 0;
            }
        }

        // Update node material for dimension
        const oldNodeMaterial = resources.nodesMesh.material as Material;
        resources.nodesMesh.material = this.createNodeMaterial(is3D);
        oldNodeMaterial.dispose();

        // Dense hubs occlude depth in 3D — fade edges further there, keep 2D at its usual opacity.
        const edgeMaterial = resources.edgesMesh.material as Material & { opacity: number };
        edgeMaterial.opacity = is3D ? EDGE_OPACITY_3D : EDGE_OPACITY;

        resources.nodesMesh.renderOrder = is3D ? BASE_RENDER_ORDER : FOREGROUND_RENDER_ORDER;
        if (this.outlineMesh) {
            this.outlineMesh.renderOrder = is3D ? BASE_RENDER_ORDER : FOREGROUND_RENDER_ORDER;
        }

        // Depth-only node proxy for 3D multi-pass edge occlusion
        if (is3D && !this.depthNodesMesh) {
            this.depthNodesMesh = this.createDepthNodesMesh(resources.scene, resources.nodesMesh);
        } else if (!is3D && this.depthNodesMesh) {
            (this.depthNodesMesh.material as Material).dispose();
            resources.scene.remove(this.depthNodesMesh);
            this.depthNodesMesh = null;
        }

        // Reset visibility — multi-pass leaves objects hidden after the last frame
        resources.nodesMesh.visible = true;
        resources.edgesMesh.visible = true;
        if (this.outlineMesh) this.outlineMesh.visible = true;
        if (this.highlightLinesObj) this.highlightLinesObj.visible = true;
        if (this.dotsMesh) this.dotsMesh.visible = true;

        // Rewrite instances in natural order — the 3D depth sort leaves them reordered — and
        // recolor them, since 3D applies a brightness factor that 2D does not.
        this.updateInstanceMatrices();
        this.updateInstanceColors();
        this.updateEdgePositions();
        this.updateHoverVisuals();
        this.updateLabelPositions();
        this.requestRender();
    }

    private createNodeMaterial(is3D: boolean): Material {
        const THREE = this.three!;
        return is3D
            ? new THREE.MeshPhongMaterial({
                  color: 0xffffff,
                  transparent: true,
                  opacity: NODE_3D_OPACITY,
                  shininess: NODE_3D_SHININESS,
              })
            : new THREE.MeshBasicMaterial({ color: 0xffffff });
    }

    private createDepthNodesMesh(scene: Scene, nodesMesh: InstancedMesh): InstancedMesh {
        const THREE = this.three!;
        const depthMaterial = new THREE.MeshBasicMaterial({ colorWrite: false });
        const depthMesh = new THREE.InstancedMesh(nodesMesh.geometry, depthMaterial, Math.max(this.nodes.length, 1));
        depthMesh.instanceMatrix = nodesMesh.instanceMatrix;
        depthMesh.frustumCulled = false;
        depthMesh.visible = false;
        scene.add(depthMesh);
        return depthMesh;
    }

    /** Write the current graph state (positions, colors, visibility, labels) into freshly created meshes. */
    private applyGraphState(): void {
        this.createLabelSprites();
        this.updateLabelPositions();
        this.updateInstanceMatrices();
        this.updateInstanceColors();
        this.updateEdgePositions();
        this.updateEdgeColors();
    }

    /** Create the node, edge, outline, depth, highlight-line and dot meshes for the current nodes/edges. */
    private createGraphMeshes(scene: Scene): { nodesMesh: InstancedMesh; edgesMesh: InstancedMesh } {
        const THREE = this.three!;
        const is3D = this.is3D;

        // Nodes (InstancedMesh)
        const geometry = new THREE.SphereGeometry(1, NODE_SPHERE_WIDTH_SEGMENTS, NODE_SPHERE_HEIGHT_SEGMENTS);
        const nodesMesh = new THREE.InstancedMesh(
            geometry,
            this.createNodeMaterial(is3D),
            Math.max(this.nodes.length, 1)
        );
        nodesMesh.instanceMatrix.setUsage(THREE.DynamicDrawUsage);
        scene.add(nodesMesh);

        // Edges — cylinder InstancedMesh for both 2D and 3D
        const edgesMesh = this.createEdgesMesh(scene);

        // Node outline mesh (BackSide rendering creates a border ring)
        const outlineGeometry = new THREE.SphereGeometry(1, NODE_SPHERE_WIDTH_SEGMENTS, NODE_SPHERE_HEIGHT_SEGMENTS);
        const outlineMaterial = new THREE.MeshBasicMaterial({ side: THREE.BackSide });
        const outlineMesh = new THREE.InstancedMesh(outlineGeometry, outlineMaterial, Math.max(this.nodes.length, 1));
        outlineMesh.frustumCulled = false;
        // Hide all outline instances initially
        const outlineDummy = new THREE.Object3D();
        outlineDummy.position.set(OFFSCREEN_POSITION, OFFSCREEN_POSITION, OFFSCREEN_POSITION);
        outlineDummy.scale.setScalar(0);
        outlineDummy.updateMatrix();
        for (let i = 0; i < Math.max(this.nodes.length, 1); i++) {
            outlineMesh.setMatrixAt(i, outlineDummy.matrix);
        }
        scene.add(outlineMesh);
        this.outlineMesh = outlineMesh;

        // Depth-only node proxy for 3D multi-pass edge occlusion
        this.depthNodesMesh = is3D ? this.createDepthNodesMesh(scene, nodesMesh) : null;

        // Highlight lines overlay (connected edges rendered brighter)
        const hlPositions = new Float32Array(this.edges.length * HIGHLIGHT_LINE_FLOATS_PER_EDGE);
        const hlGeometry = new THREE.BufferGeometry();
        hlGeometry.setAttribute('position', new THREE.Float32BufferAttribute(hlPositions, 3));
        hlGeometry.setDrawRange(0, 0);
        const hlMaterial = new THREE.LineBasicMaterial({
            color: new THREE.Color(...HIGHLIGHT_EDGE_COLOR),
            transparent: true,
            opacity: 0.5,
            depthTest: false,
        });
        const highlightLines = new THREE.LineSegments(hlGeometry, hlMaterial);
        highlightLines.frustumCulled = false;
        highlightLines.renderOrder = HIGHLIGHT_LINES_RENDER_ORDER;
        scene.add(highlightLines);
        this.highlightLinesObj = highlightLines;

        if (!is3D) {
            // 2D: nodes render on top of highlight lines
            nodesMesh.renderOrder = FOREGROUND_RENDER_ORDER;
            outlineMesh.renderOrder = FOREGROUND_RENDER_ORDER;
        }

        // Animated dots (small spheres that travel along highlighted edges)
        const maxDots = this.edges.length * DOTS_PER_EDGE;
        const dotGeometry = new THREE.SphereGeometry(1, DOT_SPHERE_WIDTH_SEGMENTS, DOT_SPHERE_HEIGHT_SEGMENTS);
        const dotMaterial = new THREE.MeshBasicMaterial({ color: 0xffffff, depthTest: false });
        const dotsMesh = new THREE.InstancedMesh(dotGeometry, dotMaterial, Math.max(maxDots, 1));
        dotsMesh.frustumCulled = false;
        dotsMesh.renderOrder = FOREGROUND_RENDER_ORDER;
        // Hide all dots initially
        const zeroDummy = new THREE.Object3D();
        zeroDummy.scale.setScalar(0);
        zeroDummy.position.set(OFFSCREEN_POSITION, OFFSCREEN_POSITION, OFFSCREEN_POSITION);
        zeroDummy.updateMatrix();
        for (let i = 0; i < maxDots; i++) {
            dotsMesh.setMatrixAt(i, zeroDummy.matrix);
        }
        scene.add(dotsMesh);
        this.dotsMesh = dotsMesh;
        this.dotsData = [];

        return { nodesMesh, edgesMesh };
    }

    private createLabelSprites(): void {
        const resources = this.resources!;
        for (const node of this.nodes) {
            const sprite = this.createLabelSprite(node.title);
            sprite.position.set(node.x, node.y + node.radius + LABEL_OFFSET_ABOVE_NODE, node.z);
            sprite.visible = this.isNodeVisible(node);
            resources.scene.add(sprite);
            resources.labelSprites.push(sprite);
        }
    }

    private disposeLabelSprites(): void {
        const resources = this.resources!;
        for (const sprite of resources.labelSprites) {
            resources.scene.remove(sprite);
            sprite.material.map?.dispose();
            sprite.material.dispose();
        }
        resources.labelSprites = [];
    }

    /** Dispose every mesh created by `createGraphMeshes`, plus the label sprites. */
    private disposeGraphMeshes(scene: Scene): void {
        const { nodesMesh, edgesMesh } = this.resources!;
        this.disposeLabelSprites();

        // Depth-only node proxy shares geometry + instanceMatrix with nodesMesh — dispose only its material
        if (this.depthNodesMesh) {
            (this.depthNodesMesh.material as Material).dispose();
            scene.remove(this.depthNodesMesh);
            this.depthNodesMesh = null;
        }

        // InstancedMesh.dispose() releases the per-instance matrix/color buffers on the GPU; geometry and material
        // disposal does not cover them, so without it every reload leaks one set per mesh. The depth proxy above
        // must not get it: it shares nodesMesh's instanceMatrix, which nodesMesh.dispose() releases here.
        for (const mesh of [nodesMesh, edgesMesh, this.outlineMesh, this.dotsMesh]) {
            if (!mesh) continue;
            mesh.geometry.dispose();
            (mesh.material as Material).dispose();
            mesh.dispose();
            scene.remove(mesh);
        }
        if (this.highlightLinesObj) {
            this.highlightLinesObj.geometry.dispose();
            (this.highlightLinesObj.material as Material).dispose();
            scene.remove(this.highlightLinesObj);
        }
        this.outlineMesh = null;
        this.highlightLinesObj = null;
        this.dotsMesh = null;
        this.dotsData = [];
        this.instancesSorted = false;
    }

    // ---- public: graph state ----

    /** Highlight specific node indices (community or search). Pass null to clear. */
    setHighlightedNodes(indices: Set<number> | null): void {
        this.highlightedIndices = indices;
        this.updateInstanceColors();
        this.requestRender();
    }

    /** Search highlight — hides non-matching/non-connected nodes entirely. Pass null to show all. */
    setSearchHighlight(indices: Set<number> | null): void {
        this.searchHighlightIndices = indices;
        if (indices !== null) {
            const visible = new Set(indices);
            for (const edge of this.edges) {
                if (indices.has(edge.sourceIndex)) visible.add(edge.targetIndex);
                if (indices.has(edge.targetIndex)) visible.add(edge.sourceIndex);
            }
            this.searchVisibleIndices = visible;
        } else {
            this.searchVisibleIndices = null;
        }
        this.applyVisibilityChange();
    }

    /** Filter by entity type. Pass null to show all. */
    setVisibleTypes(types: Set<string | null> | null): void {
        this.visibleTypeSet = types;
        this.applyVisibilityChange();
    }

    /** Color nodes by community (true) or by entity type (false). Search highlight and dimming still apply on top. */
    setColorByCommunity(enabled: boolean): void {
        this.colorByCommunity = enabled;
        this.updateInstanceColors();
        this.requestRender();
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
            // In 3D, instances may be sorted by depth — remap slot to original node index
            if (this.is3D && this.instancesSorted) {
                return this.sortedToOriginal[instanceId] ?? -1;
            }
            return instanceId;
        }
        return -1;
    }

    /** Raycast to find which edge is nearest to the given screen coordinates. Returns edge index or -1. */
    pickEdge(screenX: number, screenY: number, container: HTMLElement, threshold = EDGE_PICK_THRESHOLD_PX): number {
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

        if (edgeIndex !== null) {
            this.applyEdgeHighlight(edgeIndex);
            this.setupDots();
        } else {
            this.connectedEdgeIndices.clear();
            this.connectedNodeIndices.clear();
            this.clearDots();
        }

        this.updateEdgeColors();
        this.updateHoverVisuals();
        this.requestRender();
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
        const vector = new THREE.Vector3(node.x, node.y + node.radius + HOVER_TOOLTIP_OFFSET_ABOVE_NODE, node.z);
        vector.project(this.resources.camera);

        const rect = container.getBoundingClientRect();
        return {
            x: ((vector.x + 1) / 2) * rect.width,
            y: ((-vector.y + 1) / 2) * rect.height,
        };
    }

    /** Set which node is selected — persistent border while the detail panel is open. The label is an HTML overlay owned by the component. Pass null to clear. */
    setSelectedNode(nodeIndex: number | null): void {
        if (nodeIndex === this.selectedNodeIndex) return;
        this.selectedNodeIndex = nodeIndex;
        this.updateHoverVisuals();
        // Sprite labels hide the currently-selected one; re-run the visibility pass so switching
        // selection (including clearing it) takes effect without waiting for the next sim tick.
        this.updateLabelPositions();
        this.requestRender();
    }

    /** Component hook: fires after every rendered frame so an HTML overlay can follow the projected node. */
    setAfterRenderCallback(callback: (() => void) | null): void {
        this.afterRenderCallback = callback;
    }

    /** Whether a node's current position passes the visibility filters — used by the component to show/hide its HTML overlays. */
    isNodeIndexVisible(nodeIndex: number): boolean {
        const node = this.nodes[nodeIndex];
        return node ? this.isNodeVisible(node) : false;
    }

    /** Set which node is hovered — highlights connected edges/nodes and shows outline. Pass null to clear. */
    setHoveredNode(nodeIndex: number | null): void {
        if (nodeIndex === this.hoveredNodeIndex) return;
        this.hoveredNodeIndex = nodeIndex;
        this.hoveredEdgeIndex = null;

        if (nodeIndex !== null) {
            this.applyNodeHighlight(nodeIndex);
            this.setupDots();
        } else {
            this.connectedEdgeIndices.clear();
            this.connectedNodeIndices.clear();
            this.clearDots();
        }

        this.updateEdgeColors();
        this.updateHoverVisuals();
        // Sprite labels hide the currently-hovered one; re-run the visibility pass so entering/leaving a
        // node takes effect immediately without waiting for the next sim tick.
        this.updateLabelPositions();
        this.requestRender();
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

    /** Dispose all Three.js resources and stop rendering. Safe to call when no scene exists. */
    dispose(): void {
        if (this.frameRequestId !== null) {
            cancelAnimationFrame(this.frameRequestId);
            this.frameRequestId = null;
        }
        if (this.cameraAnimationFrameId !== null) {
            cancelAnimationFrame(this.cameraAnimationFrameId);
            this.cameraAnimationFrameId = null;
        }
        this.lastFrameTimestamp = null;

        this.resizeObserver?.disconnect();
        this.resizeObserver = null;

        if (this.resources) {
            const { renderer, scene, camera, controls } = this.resources;
            this.disposeControls(controls);
            this.disposeGraphMeshes(scene);
            this.removeLights(scene, camera);
            renderer.dispose();
            renderer.forceContextLoss();
            this.resources = null;
        }

        this.hoveredNodeIndex = null;
        this.hoveredEdgeIndex = null;
        this.selectedNodeIndex = null;
        this.depthOrderStale = true;
        this.connectedEdgeIndices.clear();
        this.connectedNodeIndices.clear();
    }

    /** Returns the color for a given entity type. */
    getTypeColor(type: string | null): string {
        if (!type) return TYPE_COLORS[0];
        return TYPE_COLORS[stableHash(type) % TYPE_COLORS.length];
    }

    /**
     * Highlight all visible nodes of an entity type and every edge touching them. Pass null to clear.
     * Driven by a filter-item hover in the sidebar — skips the connected-dots animation on purpose.
     */
    setTypeHoverHighlight(type: string | null): void {
        if (!this.resources) return;

        if (type === null) {
            if (this.typeHoverNodeIndices === null && this.connectedEdgeIndices.size === 0) return;
            this.typeHoverNodeIndices = null;
            this.connectedEdgeIndices.clear();
            this.connectedNodeIndices.clear();
            this.updateEdgeColors();
            this.updateHoverVisuals();
            this.requestRender();
            return;
        }

        const nodeIndices = new Set<number>();
        for (const node of this.nodes) {
            if (node.type === type && this.isNodeVisible(node)) {
                nodeIndices.add(node.index);
            }
        }
        const edgeIndices = new Set<number>();
        for (let i = 0; i < this.edges.length; i++) {
            const edge = this.edges[i];
            if (!nodeIndices.has(edge.sourceIndex) && !nodeIndices.has(edge.targetIndex)) continue;
            if (
                !this.isNodeVisible(this.nodes[edge.sourceIndex]) ||
                !this.isNodeVisible(this.nodes[edge.targetIndex])
            ) {
                continue;
            }
            edgeIndices.add(i);
        }

        this.typeHoverNodeIndices = nodeIndices;
        this.connectedEdgeIndices = edgeIndices;
        this.updateEdgeColors();
        this.updateHoverVisuals();
        this.requestRender();
    }

    /**
     * Smoothly animate the camera to frame all visible nodes of a type. Does nothing if no node matches.
     * Perspective: moves camera along the current view direction to a distance that fits the bounding box.
     * Orthographic: pans to the centre and adjusts `zoom` to fit.
     */
    zoomToType(type: string | null, durationMs = 400): void {
        if (!this.resources || type === null) return;
        const visibleNodes = this.nodes.filter((n) => n.type === type && this.isNodeVisible(n));
        this.fitCameraToNodes(visibleNodes, durationMs);
    }

    /**
     * Smoothly animate the camera to frame every visible node in the scene. Does nothing if nothing is visible
     * or the scene is not yet initialised. Handles both "zoomed out too far" and "some nodes off-screen".
     */
    fitToView(durationMs = 400): void {
        if (!this.resources) return;
        const visibleNodes = this.nodes.filter((n) => this.isNodeVisible(n));
        this.fitCameraToNodes(visibleNodes, durationMs);
    }

    /** Shared camera animation used by zoomToType and fitToView — see zoomToType for the per-camera behaviour. */
    private fitCameraToNodes(visibleNodes: readonly GraphNode[], durationMs: number): void {
        if (!this.resources || visibleNodes.length === 0) return;

        let minX = Infinity;
        let minY = Infinity;
        let minZ = Infinity;
        let maxX = -Infinity;
        let maxY = -Infinity;
        let maxZ = -Infinity;
        for (const n of visibleNodes) {
            if (n.x - n.radius < minX) minX = n.x - n.radius;
            if (n.y - n.radius < minY) minY = n.y - n.radius;
            if (n.z - n.radius < minZ) minZ = n.z - n.radius;
            if (n.x + n.radius > maxX) maxX = n.x + n.radius;
            if (n.y + n.radius > maxY) maxY = n.y + n.radius;
            if (n.z + n.radius > maxZ) maxZ = n.z + n.radius;
        }
        const centerX = (minX + maxX) / 2;
        const centerY = (minY + maxY) / 2;
        const centerZ = (minZ + maxZ) / 2;
        const spreadX = Math.max(1, maxX - minX);
        const spreadY = Math.max(1, maxY - minY);
        const spreadZ = Math.max(1, maxZ - minZ);

        const { camera, controls } = this.resources;
        const startTargetX = controls.target.x;
        const startTargetY = controls.target.y;
        const startTargetZ = controls.target.z;
        const startCamX = camera.position.x;
        const startCamY = camera.position.y;
        const startCamZ = camera.position.z;

        const perspective = (camera as PerspectiveCamera).isPerspectiveCamera === true;
        let endCamX: number;
        let endCamY: number;
        let endCamZ: number;
        let startZoom = 1;
        let endZoom = 1;

        if (perspective) {
            const dx = startCamX - startTargetX;
            const dy = startCamY - startTargetY;
            const dz = startCamZ - startTargetZ;
            const dist = Math.sqrt(dx * dx + dy * dy + dz * dz) || 1;
            const maxSpread = Math.max(spreadX, spreadY, spreadZ);
            const fov = ((camera as PerspectiveCamera).fov * Math.PI) / 180;
            // 1.4 leaves a bit of padding around the bounding box.
            const desiredDist = (maxSpread * 1.4) / (2 * Math.tan(fov / 2));
            endCamX = centerX + (dx / dist) * desiredDist;
            endCamY = centerY + (dy / dist) * desiredDist;
            endCamZ = centerZ + (dz / dist) * desiredDist;
        } else {
            const ortho = camera as OrthographicCamera;
            endCamX = centerX;
            endCamY = centerY;
            endCamZ = startCamZ;
            startZoom = ortho.zoom;
            const viewWidth = (ortho.right - ortho.left) / ortho.zoom;
            const viewHeight = (ortho.top - ortho.bottom) / ortho.zoom;
            const padding = 1.4;
            endZoom = Math.min(viewWidth / (spreadX * padding), viewHeight / (spreadY * padding)) * ortho.zoom;
            endZoom = Math.max(0.05, Math.min(20, endZoom));
        }

        if (this.cameraAnimationFrameId !== null) {
            cancelAnimationFrame(this.cameraAnimationFrameId);
            this.cameraAnimationFrameId = null;
        }

        const startTime = performance.now();
        const ease = (t: number): number => (t < 0.5 ? 2 * t * t : 1 - Math.pow(-2 * t + 2, 2) / 2);

        const step = (): void => {
            this.cameraAnimationFrameId = null;
            if (!this.resources) return;
            const now = performance.now();
            const t = Math.min(1, (now - startTime) / durationMs);
            const e = ease(t);

            controls.target.x = startTargetX + (centerX - startTargetX) * e;
            controls.target.y = startTargetY + (centerY - startTargetY) * e;
            controls.target.z = startTargetZ + (centerZ - startTargetZ) * e;
            camera.position.x = startCamX + (endCamX - startCamX) * e;
            camera.position.y = startCamY + (endCamY - startCamY) * e;
            camera.position.z = startCamZ + (endCamZ - startCamZ) * e;
            if (!perspective) {
                const ortho = camera as OrthographicCamera;
                ortho.zoom = startZoom + (endZoom - startZoom) * e;
                ortho.updateProjectionMatrix();
            }
            this.depthOrderStale = true;
            this.requestRender();

            if (t < 1) {
                this.cameraAnimationFrameId = this.ngZone.runOutsideAngular(() => requestAnimationFrame(step));
            }
        };

        this.cameraAnimationFrameId = this.ngZone.runOutsideAngular(() => requestAnimationFrame(step));
    }

    // ---- private ----

    private setupConstantDolly(canvas: HTMLCanvasElement, camera: Camera, controls: OrbitControlsLike): void {
        const THREE = this.three!;
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
            const direction = raycaster.ray.direction.clone().multiplyScalar(sign * DOLLY_SPEED);

            camera.position.x += direction.x;
            camera.position.y += direction.y;
            camera.position.z += direction.z;
            controls.target.x += direction.x;
            controls.target.y += direction.y;
            controls.target.z += direction.z;
            this.depthOrderStale = true;
            this.requestRender();
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
            const camera = new THREE.PerspectiveCamera(
                CAMERA_FIELD_OF_VIEW_DEGREES,
                width / height,
                CAMERA_NEAR_PLANE,
                CAMERA_FAR_PLANE
            );
            camera.position.set(0, 0, PERSPECTIVE_CAMERA_DISTANCE);
            return camera;
        } else {
            const halfW = width / 2;
            const halfH = height / 2;
            const camera = new THREE.OrthographicCamera(
                -halfW,
                halfW,
                halfH,
                -halfH,
                CAMERA_NEAR_PLANE,
                CAMERA_FAR_PLANE
            );
            camera.position.set(0, 0, ORTHOGRAPHIC_CAMERA_DISTANCE);
            camera.lookAt(0, 0, 0);
            return camera;
        }
    }

    private isNodeVisible(node: GraphNode): boolean {
        if (this.visibleTypeSet && !this.visibleTypeSet.has(node.type)) {
            return false;
        }
        if (this.searchVisibleIndices !== null && !this.searchVisibleIndices.has(node.index)) {
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
                dummy.position.set(OFFSCREEN_POSITION, OFFSCREEN_POSITION, OFFSCREEN_POSITION);
                dummy.scale.setScalar(0);
            }
            dummy.updateMatrix();
            this.resources.nodesMesh.setMatrixAt(i, dummy.matrix);
        }
        this.resources.nodesMesh.instanceMatrix.needsUpdate = true;
        this.resources.nodesMesh.computeBoundingSphere();
        this.instancesSorted = false;
        this.depthOrderStale = true;
    }

    /** Re-apply node/edge/label visibility after the type filter or search set changed. */
    private applyVisibilityChange(): void {
        this.updateInstanceMatrices();
        this.updateInstanceColors();
        this.updateEdgePositions();
        this.updateLabelPositions();
        this.requestRender();
    }

    private getNodeColor(nodeIndex: number): ColorTuple {
        const node = this.nodes[nodeIndex];
        const baseColor = this.colorByCommunity ? node.communityColor : node.color;
        if (this.searchHighlightIndices !== null) {
            return this.searchHighlightIndices.has(nodeIndex) ? HIGHLIGHT_COLOR : baseColor;
        }
        if (this.highlightedIndices !== null) {
            return this.highlightedIndices.has(nodeIndex)
                ? HIGHLIGHT_COLOR
                : [baseColor[0] * DIMMED_ALPHA, baseColor[1] * DIMMED_ALPHA, baseColor[2] * DIMMED_ALPHA];
        }
        return baseColor;
    }

    private updateInstanceColors(): void {
        if (!this.resources || !this.three) return;
        const THREE = this.three;
        const tempColor = new THREE.Color();
        const bright = this.is3D ? NODE_3D_BRIGHTNESS : 1;

        for (let i = 0; i < this.nodes.length; i++) {
            const color = this.getNodeColor(i);
            tempColor.setRGB(color[0] * bright, color[1] * bright, color[2] * bright);
            this.resources.nodesMesh.setColorAt(i, tempColor);
        }
        if (this.resources.nodesMesh.instanceColor) {
            this.resources.nodesMesh.instanceColor.needsUpdate = true;
        }
        // Colors were written in natural order; the 3D pass must re-sort them alongside the matrices.
        this.depthOrderStale = true;
    }

    private createEdgesMesh(scene: Scene): InstancedMesh {
        const THREE = this.three!;
        const minRadius = this.nodes.reduce((min, n) => Math.min(min, n.radius), Infinity);
        this.edgeRadius = minRadius * EDGE_WIDTH_RATIO;
        const cylGeometry = new THREE.CylinderGeometry(1, 1, 1, EDGE_CYLINDER_RADIAL_SEGMENTS);
        const cylMaterial = new THREE.MeshBasicMaterial({
            transparent: true,
            opacity: this.is3D ? EDGE_OPACITY_3D : EDGE_OPACITY,
        });
        const edgesMesh = new THREE.InstancedMesh(cylGeometry, cylMaterial, Math.max(this.edges.length, 1));
        edgesMesh.instanceMatrix.setUsage(THREE.DynamicDrawUsage);
        edgesMesh.frustumCulled = false;
        scene.add(edgesMesh);
        return edgesMesh;
    }

    private updateEdgePositions(): void {
        if (!this.resources || !this.three) return;
        const THREE = this.three;
        const edgesMesh = this.resources.edgesMesh;
        const dummy = new THREE.Object3D();
        const up = new THREE.Vector3(0, 1, 0);
        const dir = new THREE.Vector3();
        const quat = new THREE.Quaternion();
        const radius = this.edgeRadius;

        let visibleCount = 0;
        for (const edge of this.edges) {
            const src = this.nodes[edge.sourceIndex];
            const tgt = this.nodes[edge.targetIndex];
            if (!this.isNodeVisible(src) || !this.isNodeVisible(tgt)) {
                dummy.position.set(OFFSCREEN_POSITION, OFFSCREEN_POSITION, OFFSCREEN_POSITION);
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

            if (segLen < MIN_EDGE_SEGMENT_LENGTH) {
                dummy.position.set(OFFSCREEN_POSITION, OFFSCREEN_POSITION, OFFSCREEN_POSITION);
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
        dummy.position.set(OFFSCREEN_POSITION, OFFSCREEN_POSITION, OFFSCREEN_POSITION);
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
        const { camera, labelSprites, renderer } = this.resources;
        const perspective = (camera as PerspectiveCamera).isPerspectiveCamera === true;
        const zoom = perspective ? 0 : (camera as OrthographicCamera).zoom;
        const cameraInverse = perspective ? camera.matrixWorldInverse : null;
        const nodeInView = perspective ? new this.three!.Vector3() : null;
        // Half the canvas height in device-independent pixels; perspective projection maps a world
        // segment of length `L` at view depth `d` to `L · halfHeightPx / (d · tan(fov/2))` pixels.
        const halfHeightPx = perspective ? renderer.domElement.clientHeight / 2 : 0;
        const tanHalfFov = perspective ? Math.tan(((camera as PerspectiveCamera).fov * Math.PI) / 360) : 0;
        // Reference radius used for the 3D culling metric: by using a fixed radius instead of each
        // node's own, visibility depends solely on view depth, so a bigger-but-farther node can never
        // win a label while a smaller-but-closer one has none.
        const referenceRadius3D = NODE_MIN_RADIUS;
        // 2D radius pivot: the influence coefficient blends each node's radius toward this midpoint, so
        // a node whose radius equals the midpoint keeps the same toggle zoom regardless of the setting.
        const midpointRadius2D = (NODE_MIN_RADIUS + NODE_MAX_RADIUS) / 2;

        for (let i = 0; i < labelSprites.length && i < this.nodes.length; i++) {
            const node = this.nodes[i];
            const sprite = labelSprites[i];
            sprite.position.set(node.x, node.y + node.radius + LABEL_OFFSET_ABOVE_NODE, node.z);
            // Hide the sprite label for the selected or hovered node — their HTML overlays already show
            // the title (in the accent-purple style), and keeping both would stack two pills over the node.
            const allowedByNode =
                i !== this.selectedNodeIndex && i !== this.hoveredNodeIndex && this.isNodeVisible(node);
            if (!allowedByNode) {
                sprite.visible = false;
                continue;
            }

            if (perspective) {
                // Pixel radius of a reference-sized node at this node's view depth; view-depth-based
                // so panning (which does not change view depth) leaves labels alone, and the reference
                // radius makes the metric node-size-independent.
                nodeInView!.set(node.x, node.y, node.z).applyMatrix4(cameraInverse!);
                const viewDepth = -nodeInView!.z;
                const pixelRadius = viewDepth > 0 ? (referenceRadius3D * halfHeightPx) / (viewDepth * tanHalfFov) : 0;
                sprite.visible = pixelRadius > LABEL_MIN_NODE_PIXEL_RADIUS_3D;
                // Restore base world-space scale; a prior 2D pass may have shrunk it to counter ortho zoom.
                sprite.scale.set(sprite.userData['baseScaleX'], sprite.userData['baseScaleY'], 1);
            } else {
                // 2D ortho: 1 world unit = 1 pixel at zoom = 1, so pixel radius = radius × zoom.
                // Influence coefficient dampens how strongly node size spreads the toggle zoom across nodes.
                const effectiveRadius = midpointRadius2D + (node.radius - midpointRadius2D) * LABEL_SIZE_INFLUENCE_2D;
                sprite.visible = effectiveRadius * zoom > LABEL_MIN_NODE_PIXEL_RADIUS_2D;
                // Keep labels at a constant on-screen size in 2D by countering the ortho zoom: world
                // extent of a pixel = 1 / zoom, so scale = baseScale / zoom renders at a fixed pixel size.
                const screenSizeScale = LABEL_SCREEN_SIZE_SCALE_2D / zoom;
                sprite.scale.set(
                    sprite.userData['baseScaleX'] * screenSizeScale,
                    sprite.userData['baseScaleY'] * screenSizeScale,
                    1
                );
            }
        }
    }

    private createLabelSprite(text: string): Sprite {
        const THREE = this.three!;
        const font = `${LABEL_FONT_WEIGHT} ${LABEL_FONT_SIZE}px ${LABEL_FONT_FAMILY}`;

        // Measure text width first
        const measureCanvas = document.createElement('canvas');
        const measureCtx = measureCanvas.getContext('2d')!;
        measureCtx.font = font;
        const textWidth = measureCtx.measureText(text).width;

        const canvasWidth = Math.ceil(textWidth + LABEL_HORIZONTAL_PADDING * 2);
        const canvasHeight = LABEL_CANVAS_HEIGHT;

        const canvas = document.createElement('canvas');
        canvas.width = canvasWidth;
        canvas.height = canvasHeight;
        const context = canvas.getContext('2d')!;

        // Background pill — inset by half the stroke so the border is drawn fully inside the canvas.
        const borderWidth = LABEL_BORDER_WIDTH;
        const strokeInset = borderWidth / 2;
        const pillWidth = canvasWidth - borderWidth;
        const pillHeight = canvasHeight - borderWidth;
        const radius = pillHeight / 2;
        context.beginPath();
        context.roundRect(strokeInset, strokeInset, pillWidth, pillHeight, radius);
        context.fillStyle = LABEL_BACKGROUND_COLOR;
        context.fill();
        context.lineWidth = borderWidth;
        context.strokeStyle = LABEL_BORDER_COLOR;
        context.stroke();

        // Text
        context.font = font;
        context.fillStyle = LABEL_TEXT_COLOR;
        context.textAlign = 'center';
        context.textBaseline = 'middle';
        context.fillText(text, canvasWidth / 2, canvasHeight / 2);

        const texture = new THREE.CanvasTexture(canvas);
        // Canvas 2D paints in sRGB; without this three.js treats the texels as linear and the
        // renderer's sRGB output re-encodes them, lightening every pill color.
        texture.colorSpace = THREE.SRGBColorSpace;
        texture.needsUpdate = true;
        // `transparent` lands the sprite in three.js's transparent render group — otherwise alphaTest
        // alone marks it opaque, and three.js draws opaque before transparent, so the semi-transparent
        // nodes in the 3D pass end up blending over the "opaque" pill.
        // `alphaTest` still discards the fully transparent canvas pixels outside the pill, so the pill
        // stays sharp instead of blending a halo.
        const material = new THREE.SpriteMaterial({
            map: texture,
            transparent: true,
            alphaTest: 0.5,
            depthTest: false,
        });
        const sprite = new THREE.Sprite(material);
        // Scale proportional to canvas aspect ratio. The base scale is stashed on `userData` so the 2D
        // branch of `updateLabelPositions` can counter the ortho zoom and keep the pill at a constant
        // on-screen size, while 3D keeps the raw world-size scaling for natural perspective shrinkage.
        const spriteWidth = LABEL_SPRITE_HEIGHT * (canvasWidth / canvasHeight);
        sprite.scale.set(spriteWidth, LABEL_SPRITE_HEIGHT, 1);
        sprite.userData['baseScaleX'] = spriteWidth;
        sprite.userData['baseScaleY'] = LABEL_SPRITE_HEIGHT;
        // Within transparent group, higher renderOrder draws later — so the pill sits on top of the
        // back-to-front-sorted node mesh in the 3D multi-pass.
        sprite.renderOrder = FOREGROUND_RENDER_ORDER;
        return sprite;
    }

    private applyNodeHighlight(nodeIndex: number): void {
        this.connectedEdgeIndices.clear();
        this.connectedNodeIndices.clear();
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

    private applyEdgeHighlight(edgeIndex: number): void {
        this.connectedEdgeIndices.clear();
        this.connectedNodeIndices.clear();
        const edge = this.edges[edgeIndex];
        this.connectedEdgeIndices.add(edgeIndex);
        this.connectedNodeIndices.add(edge.sourceIndex);
        this.connectedNodeIndices.add(edge.targetIndex);
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

                if (!this.isNodeVisible(node)) {
                    // Skip hidden nodes — no outline
                } else if (
                    i === this.hoveredNodeIndex ||
                    i === this.selectedNodeIndex ||
                    this.typeHoverNodeIndices?.has(i)
                ) {
                    borderColor = HOVERED_BORDER_COLOR;
                }

                if (borderColor) {
                    dummy.position.set(node.x, node.y, node.z);
                    dummy.scale.setScalar(node.radius * OUTLINE_SCALE);
                    tempColor.setRGB(borderColor[0], borderColor[1], borderColor[2]);
                } else {
                    dummy.position.set(OFFSCREEN_POSITION, OFFSCREEN_POSITION, OFFSCREEN_POSITION);
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
                    if (!this.isNodeVisible(src) || !this.isNodeVisible(tgt)) continue;
                    const dx = tgt.x - src.x;
                    const dy = tgt.y - src.y;
                    const dz = tgt.z - src.z;
                    const len = Math.sqrt(dx * dx + dy * dy + dz * dz) || 1;
                    const nx = dx / len;
                    const ny = dy / len;
                    const nz = dz / len;
                    const offset = count * HIGHLIGHT_LINE_FLOATS_PER_EDGE;
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
        if (!this.resources || !this.three) return;

        const edgesMesh = this.resources.edgesMesh;
        const tempColor = new this.three.Color();

        for (let i = 0; i < this.edges.length; i++) {
            const color: ColorTuple = this.connectedEdgeIndices.has(i) ? HIGHLIGHT_EDGE_COLOR : EDGE_COLOR;
            tempColor.setRGB(color[0], color[1], color[2]);
            edgesMesh.setColorAt(i, tempColor);
        }
        if (edgesMesh.instanceColor) {
            edgesMesh.instanceColor.needsUpdate = true;
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
        this.requestRender();
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
            const edge = this.edges[edgeIdx];
            if (
                !this.isNodeVisible(this.nodes[edge.sourceIndex]) ||
                !this.isNodeVisible(this.nodes[edge.targetIndex])
            ) {
                continue;
            }
            for (let d = 0; d < DOTS_PER_EDGE; d++) {
                this.dotsData.push({
                    edgeIndex: edgeIdx,
                    t: d / DOTS_PER_EDGE,
                    speed: DOT_SPEED,
                });
            }
        }
    }

    /** Advance the dots along their edges by `deltaSeconds` of animation time. */
    private updateDots(deltaSeconds: number): void {
        if (!this.dotsMesh || !this.three || this.dotsData.length === 0) return;
        const THREE = this.three;
        const dummy = new THREE.Object3D();

        for (let i = 0; i < this.dotsData.length; i++) {
            const dot = this.dotsData[i];
            dot.t += dot.speed * deltaSeconds;
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
        zeroDummy.position.set(OFFSCREEN_POSITION, OFFSCREEN_POSITION, OFFSCREEN_POSITION);
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
        zeroDummy.position.set(OFFSCREEN_POSITION, OFFSCREEN_POSITION, OFFSCREEN_POSITION);
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
                dummy.position.set(OFFSCREEN_POSITION, OFFSCREEN_POSITION, OFFSCREEN_POSITION);
                dummy.scale.setScalar(0);
            }
            dummy.updateMatrix();
            nodesMesh.setMatrixAt(slot, dummy.matrix);

            const color = this.getNodeColor(nodeIndex);
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
        this.instancesSorted = true;
    }

    /**
     * Draw one frame. Keeps requesting frames only while dots are animating; everything else
     * (simulation ticks, camera moves, hover, filters, resize) calls `requestRender` itself.
     */
    private renderFrame(timestamp: number): void {
        this.frameRequestId = null;
        if (!this.resources) return;

        const deltaSeconds =
            this.lastFrameTimestamp === null
                ? 0
                : Math.min((timestamp - this.lastFrameTimestamp) / 1000, MAX_FRAME_DELTA_SECONDS);

        this.resources.controls.update();
        if (this.dotsData.length > 0) {
            this.updateDots(deltaSeconds);
        }
        if (this.is3D && this.depthNodesMesh) {
            this.render3DMultiPass();
        } else {
            this.resources.renderer.render(this.resources.scene, this.resources.camera);
        }

        if (this.dotsData.length > 0) {
            this.lastFrameTimestamp = timestamp;
            this.requestRender();
        } else {
            this.lastFrameTimestamp = null;
        }

        // After the frame is on screen, let the component reposition HTML overlays that follow projected nodes.
        this.afterRenderCallback?.();
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
        const { renderer, scene, camera, nodesMesh, edgesMesh, labelSprites } = this.resources!;
        const depthMesh = this.depthNodesMesh!;
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

        // Sort node instances back-to-front for correct transparent blending — only when the
        // camera, positions, colors or visibility changed since the last sort
        if (this.depthOrderStale) {
            this.sortInstancesByDepth();
            this.depthOrderStale = false;
        }

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

        // Restore label visibility after multi-pass (Pass 3 hides them)
        labelSprites.forEach((s, i) => {
            s.visible = savedLabelVis[i];
        });

        scene.background = savedBackground;
        renderer.autoClear = prevAutoClear;
    }
}
