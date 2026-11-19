import { ColorTuple } from './graph-scene.model';

/** Position used to move hidden instances offscreen. */
export const OFFSCREEN_POSITION = 99999;

/** Scene background color. */
export const SCENE_BACKGROUND = 0x000000;

/** Upper bound for the renderer pixel ratio, so high-DPI screens do not render at 3x or more. */
export const MAX_PIXEL_RATIO = 2;

/** Label pill colors (approximates --tooltip-bg and --color-text-primary). */
export const LABEL_BACKGROUND_COLOR = 'rgba(30, 30, 34, 1)';
export const LABEL_TEXT_COLOR = '#e8e8ec';

/** Stable color palette for entity types — high-saturation, high-contrast hues. */
export const TYPE_COLORS: readonly string[] = [
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

/**
 * Community colors are generated, not picked from a palette, because a graph can have far more communities
 * than any palette has entries. The hue comes from the id's hash stepped by the golden angle, so ids that hash
 * to neighboring values (sequential ids such as "1", "2", "3") still land on well-separated hues.
 */
export const COMMUNITY_HUE_STEP_DEGREES = 137.508;
export const COMMUNITY_COLOR_SATURATION = 0.85;
export const COMMUNITY_COLOR_LIGHTNESS = 0.55;
/**
 * Hue band no community is drawn in, so none looks like the yellow search highlight (HIGHLIGHT_COLOR, about 56°).
 * Wider than yellow itself: in 3D, NODE_3D_BRIGHTNESS doubles every channel and clamps, which turns oranges and
 * yellow-greens yellow as well.
 */
export const COMMUNITY_EXCLUDED_HUE_START_DEGREES = 20;
export const COMMUNITY_EXCLUDED_HUE_END_DEGREES = 100;

/** Neutral gray for nodes without a community in community color mode — reads as "unassigned", not as a community. */
export const NO_COMMUNITY_COLOR: ColorTuple = [0.45, 0.45, 0.5];

export const HIGHLIGHT_COLOR: ColorTuple = [1.0, 0.95, 0.2]; // yellow highlight
export const DIMMED_ALPHA = 0.15;
export const LABEL_FONT_SIZE = 24;
export const LABEL_FONT_FAMILY = 'Inter, sans-serif';
export const LABEL_CANVAS_HEIGHT = 36;
/** Space between the label text and the ends of its pill, in canvas pixels. */
export const LABEL_HORIZONTAL_PADDING = 12;
/** Label sprite height in world units; the width follows the canvas aspect ratio. */
export const LABEL_SPRITE_HEIGHT = 8;
/** Gap between a node's top edge and its label, in world units. */
export const LABEL_OFFSET_ABOVE_NODE = 4;
/** Gap between a node's top edge and the anchor of its hover tooltip, in world units. */
export const HOVER_TOOLTIP_OFFSET_ABOVE_NODE = 2;

/** Node radius range in world units; a node's radius grows linearly with its degree. */
export const NODE_MIN_RADIUS = 4;
export const NODE_MAX_RADIUS = 16;

/** Sphere tessellation of the node and node-outline meshes — both must match so the outline wraps the node. */
export const NODE_SPHERE_WIDTH_SEGMENTS = 16;
export const NODE_SPHERE_HEIGHT_SEGMENTS = 12;
/** Sphere tessellation of the animated dots — smaller than nodes, so fewer segments suffice. */
export const DOT_SPHERE_WIDTH_SEGMENTS = 8;
export const DOT_SPHERE_HEIGHT_SEGMENTS = 6;
/** Sides of the cylinder each edge is drawn as. */
export const EDGE_CYLINDER_RADIAL_SEGMENTS = 6;
/** Edges shorter than this (overlapping nodes) are hidden instead of drawn as a degenerate cylinder. */
export const MIN_EDGE_SEGMENT_LENGTH = 0.01;
/** Floats per highlight-line segment: two endpoints of x, y, z. */
export const HIGHLIGHT_LINE_FLOATS_PER_EDGE = 6;

/** Default edge color; connected edges switch to HIGHLIGHT_EDGE_COLOR while a node or edge is hovered. */
export const EDGE_COLOR: ColorTuple = [0.5, 0.5, 0.55];

/** Hover colors — the hovered node's outline and its connected edges. */
export const HOVERED_BORDER_COLOR: ColorTuple = [0.42, 0.45, 0.98]; // accent / indigo
export const HIGHLIGHT_EDGE_COLOR: ColorTuple = [0.75, 0.6, 0.15]; // deeper amber
export const OUTLINE_SCALE = 1.35; // how much larger the outline ring is vs the node
export const DOTS_PER_EDGE = 3;
export const DOT_RADIUS = 1.5;
export const DOT_SPEED = 0.4; // 0..1 per second

/** Longest frame step the dot animation advances by, so a stalled tab does not make dots jump. */
export const MAX_FRAME_DELTA_SECONDS = 0.1;

/** Hover-pick distance for edges: the pointer must be within this many screen pixels of an edge. */
export const EDGE_PICK_THRESHOLD_PX = 6;

/**
 * Draw order of the scene layers. In 2D, nodes, outlines and dots sit above the highlight lines;
 * in 3D, nodes and outlines use the base order and the multi-pass render handles occlusion.
 */
export const BASE_RENDER_ORDER = 0;
export const HIGHLIGHT_LINES_RENDER_ORDER = 1;
export const FOREGROUND_RENDER_ORDER = 2;

/** Camera setup. The 2D camera is orthographic, the 3D one perspective; both share the clipping range. */
export const CAMERA_FIELD_OF_VIEW_DEGREES = 60;
export const CAMERA_NEAR_PLANE = 1;
export const CAMERA_FAR_PLANE = 5000;
export const PERSPECTIVE_CAMERA_DISTANCE = 300;
export const ORTHOGRAPHIC_CAMERA_DISTANCE = 500;

/** World units the 3D camera moves per wheel step (constant speed, unlike OrbitControls zoom). */
export const DOLLY_SPEED = 15;

/** Node opacity in 3D mode (0..1). Lower = more see-through between overlapping nodes. */
export const NODE_3D_OPACITY = 0.75;

/** Specular highlight sharpness of 3D nodes (Phong shininess). */
export const NODE_3D_SHININESS = 40;

/**
 * Edge opacity (0..1). Lower = more transparent connections. Low, so dense hubs stay readable; highlighted edges
 * stay at full strength because the opaque highlight lines are drawn over them.
 */
export const EDGE_OPACITY = 0.25;

/** Edge opacity in 3D, lower than 2D so dense hubs do not obscure the depth cues behind them. */
export const EDGE_OPACITY_3D = 0.1;

/** Edge width as a fraction of the smallest node's radius. */
export const EDGE_WIDTH_RATIO = 0.1;

/** 3D lighting intensities. Ambient lights all faces equally; directional creates the 3D gradient. */
export const AMBIENT_LIGHT_INTENSITY = 0.4; // shadow-side base brightness
export const DIRECTIONAL_LIGHT_INTENSITY = 1.6; // strong lit-vs-shadow contrast across the sphere

/** Directional light position relative to the camera it is attached to — lights nodes from above-front. */
export const DIRECTIONAL_LIGHT_POSITION: readonly [number, number, number] = [0, 50, 100];

/** Object names the 3D lights are added under, so they can be found and removed again. */
export const AMBIENT_LIGHT_NAME = 'graphAmbient';
export const DIRECTIONAL_LIGHT_NAME = 'graphDirectional';

/**
 * 3D instance color multiplier — compensates for brightness lost to alpha blending
 * against the dark background. 1.0 = unmodified, 2.0 = 100 % brighter (GPU clamps to 1.0).
 */
export const NODE_3D_BRIGHTNESS = 2.0;

/** Width of the random square (cube in 3D) new nodes are scattered in before the layout runs, in world units. */
export const INITIAL_LAYOUT_SPREAD = 200;

/** Force-layout tuning: target edge length and node repulsion (negative = nodes push each other apart). */
export const SIMULATION_LINK_DISTANCE = 40;
export const SIMULATION_CHARGE_STRENGTH = -150;
/** Gap the layout keeps between the surfaces of two nodes, in world units, so no node is drawn over another. */
export const SIMULATION_COLLISION_PADDING = 2;

/**
 * Community grouping: each tick a node's velocity moves by `(centroid − position) × strength × alpha`, toward
 * the current centroid of its community. Below 1, so a node never overshoots its centroid in one tick.
 */
export const COMMUNITY_CLUSTER_STRENGTH = 0.2;

/** Multiplier on the strength of links between two different communities while grouping, so clusters pull apart. */
export const INTER_COMMUNITY_LINK_STRENGTH_FACTOR = 0.1;

/** Simulation energy restored when a node is grabbed, so the layout reacts to the drag. */
export const DRAG_REHEAT_ALPHA = 0.3;
