import { ColorTuple } from './graph-scene.model';

/** Position used to move hidden instances offscreen. */
export const OFFSCREEN_POS = 99999;

/** Scene background color. */
export const SCENE_BACKGROUND = 0x000000;

/** Label pill colors (approximates --tooltip-bg and --color-text-primary). */
export const LABEL_BG_COLOR = 'rgba(30, 30, 34, 1)';
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

export const HIGHLIGHT_COLOR: ColorTuple = [1.0, 0.95, 0.2]; // yellow highlight
export const DIMMED_ALPHA = 0.15;
export const LABEL_FONT_SIZE = 24;
export const LABEL_CANVAS_HEIGHT = 36;

/** Hover outline colors — adjust these three to change the look. */
export const HOVERED_BORDER_COLOR: ColorTuple = [0.42, 0.45, 0.98]; // accent / indigo
export const CONNECTED_BORDER_COLOR: ColorTuple = [0.3, 0.75, 0.55]; // teal-green
export const HIGHLIGHT_EDGE_COLOR: ColorTuple = [1.0, 0.95, 0.4]; // bright yellow
export const OUTLINE_SCALE = 1.35; // how much larger the outline ring is vs the node
export const DOTS_PER_EDGE = 3;
export const DOT_RADIUS = 1.5;
export const DOT_SPEED = 0.4; // 0..1 per second

/** Node opacity in 3D mode (0..1). Lower = more see-through between overlapping nodes. */
export const NODE_3D_OPACITY = 0.75;

/** Edge opacity (0..1). Lower = more transparent connections. */
export const EDGE_OPACITY = 0.6;

/** Edge width as a fraction of the smallest node's radius. */
export const EDGE_WIDTH_RATIO = 0.1;

/** 3D lighting intensities. Ambient lights all faces equally; directional creates the 3D gradient. */
export const AMBIENT_LIGHT_INTENSITY = 0.4; // shadow-side base brightness
export const DIRECTIONAL_LIGHT_INTENSITY = 1.6; // strong lit-vs-shadow contrast across the sphere

/**
 * 3D instance color multiplier — compensates for brightness lost to alpha blending
 * against the dark background. 1.0 = unmodified, 2.0 = 100 % brighter (GPU clamps to 1.0).
 */
export const NODE_3D_BRIGHTNESS = 2.0;
