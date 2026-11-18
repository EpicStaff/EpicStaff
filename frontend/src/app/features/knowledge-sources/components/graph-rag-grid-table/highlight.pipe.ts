import { Pipe, PipeTransform } from '@angular/core';
import { escapeHtml } from '@shared/utils';

const REGEXP_SPECIAL_CHARACTERS = /[.*+?^${}()|[\]\\]/g;

/** Class on every highlight `<mark>`; the grid stylesheet targets it. */
export const HIGHLIGHT_CLASS = 'grid-table-highlight';

/**
 * Renders a cell value as safe HTML with every case-insensitive occurrence of `searchTerm` wrapped in
 * `<mark class="grid-table-highlight">`. The class scopes the grid's highlight style to these marks only
 * (the sanitizer keeps `class` on `[innerHTML]` output).
 *
 * The raw text is split on the term first and each piece is escaped afterwards, so the term is matched
 * against what the user sees (a search for `&` matches `&`, not the `&amp;` entity) and no markup can leak in.
 */
@Pipe({
    name: 'highlight',
})
export class HighlightPipe implements PipeTransform {
    transform(value: unknown, searchTerm: string): string {
        const text = value == null ? '' : String(value);
        if (!searchTerm) {
            return escapeHtml(text);
        }

        const escapedTerm = searchTerm.replace(REGEXP_SPECIAL_CHARACTERS, '\\$&');
        // The capturing group keeps the matches in the result: odd indexes are matches, even ones the text between.
        return text
            .split(new RegExp(`(${escapedTerm})`, 'gi'))
            .map((piece, index) =>
                index % 2 === 1 ? `<mark class="${HIGHLIGHT_CLASS}">${escapeHtml(piece)}</mark>` : escapeHtml(piece)
            )
            .join('');
    }
}
