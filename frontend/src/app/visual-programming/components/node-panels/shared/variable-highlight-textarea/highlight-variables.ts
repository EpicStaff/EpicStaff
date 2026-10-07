const PLACEHOLDER = /\{([^{}\s]+)\}/g;

/**
 * The backdrop HTML of a highlight field: `text` escaped, with each `{name}` that `isVariable`
 * accepts wrapped in a `.vht-variable` span. Any other `{…}` stays plain text. The text is escaped
 * first, so `isVariable` receives the name already HTML-escaped (`a&b` arrives as `a&amp;b`).
 */
export function highlightVariablesHtml(text: string, isVariable: (name: string) => boolean): string {
    return escapeHtml(text).replace(PLACEHOLDER, (match, name: string) =>
        isVariable(name) ? `<span class="vht-variable">${match}</span>` : match
    );
}

function escapeHtml(text: string): string {
    return text
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#039;');
}
