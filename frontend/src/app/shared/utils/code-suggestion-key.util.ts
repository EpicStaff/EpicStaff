/**
 * The key that opens suggestions in a Monaco code editor, as a hint shows it. Monaco's Mac default, ⌃Space, is
 * taken by macOS (input source switch), so the Mac hint names ⌘I, Monaco's other key for it.
 *
 *  codeSuggestionKeyLabel(false) → 'Ctrl+Space'
 *  codeSuggestionKeyLabel(true)  → '⌘I'
 */
export function codeSuggestionKeyLabel(isMac: boolean): string {
    return isMac ? '⌘I' : 'Ctrl+Space';
}
