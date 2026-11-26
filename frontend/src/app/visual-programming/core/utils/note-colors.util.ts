import { LABEL_COLOR_OPTIONS, NODE_COLORS, NodeType } from '@shared/models';

/**
 * Fill options for graph notes, derived from the label colour palette
 * so notes and labels share the same visual language.
 */
export const NOTE_COLORS: readonly string[] = [
    NODE_COLORS[NodeType.NOTE],
    ...LABEL_COLOR_OPTIONS.map((option) => option.circleBg),
];

/** The only form the colour picker and the defaults produce; the backend accepts the same. */
const NOTE_COLOR_PATTERN = /^#[0-9a-fA-F]{6}$/;

/**
 * The stored note colour when it is a `#RRGGBB` hex colour, otherwise `undefined` so the note falls back to the
 * default colour. The colour is drawn as a CSS value: anything wider (`url(...)`, a keyword list) would let a flow
 * make every viewer's browser fetch an outside URL. Kept a hex pattern on purpose, never a CSS parser.
 */
export function safeNoteColor(value: unknown): string | undefined {
    return typeof value === 'string' && NOTE_COLOR_PATTERN.test(value) ? value : undefined;
}
