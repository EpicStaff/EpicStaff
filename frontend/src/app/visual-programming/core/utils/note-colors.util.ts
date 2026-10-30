import { LABEL_COLOR_OPTIONS } from '@shared/models';

/**
 * Fill options for graph notes, derived from the label colour palette
 * so notes and labels share the same visual language.
 */
export const NOTE_COLORS: readonly string[] = LABEL_COLOR_OPTIONS.map((option) => option.circleBg);

/**
 * Returns the note fill colour that is associated with the given user id.
 * The mapping is stable: the same id always produces the same colour.
 */
export function noteColorFromUserId(userId: number): string {
    return NOTE_COLORS[Math.abs(userId) % NOTE_COLORS.length];
}
