import { LABEL_COLOR_OPTIONS, NODE_COLORS, NodeType } from '@shared/models';

/**
 * Fill options for graph notes, derived from the label colour palette
 * so notes and labels share the same visual language.
 */
export const NOTE_COLORS: readonly string[] = [
    NODE_COLORS[NodeType.NOTE],
    ...LABEL_COLOR_OPTIONS.map((option) => option.circleBg),
];
