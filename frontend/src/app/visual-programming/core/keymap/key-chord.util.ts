export type KeyChord = string;

export type ChordRejection = 'invalid' | 'mac-ctrl' | 'reserved' | 'bare-key' | 'taken';

export const RESERVED_CHORDS: ReadonlySet<KeyChord> = new Set([
    'Mod+KeyS',
    'Mod+KeyZ',
    'Mod+KeyY',
    'Mod+KeyF',
    'Delete',
    'Escape',
    'Mod+KeyW',
    'Mod+KeyT',
    'Mod+KeyN',
    'Mod+Shift+KeyT',
    'Mod+Shift+KeyN',
    'Mod+Shift+KeyW',
    'Shift+Tab',
    'Shift+Space',
    'Shift+Enter',
]);

const MODIFIER_CODES: ReadonlySet<string> = new Set([
    'ShiftLeft',
    'ShiftRight',
    'ControlLeft',
    'ControlRight',
    'AltLeft',
    'AltRight',
    'MetaLeft',
    'MetaRight',
    'OSLeft',
    'OSRight',
]);

const MODIFIER_TOKENS: ReadonlySet<string> = new Set(['Mod', 'Ctrl', 'Alt', 'Shift', 'Meta']);

const WELL_FORMED_CHORD = /^(?:Mod\+)?(?:Ctrl\+)?(?:Alt\+)?(?:Shift\+)?([A-Z][A-Za-z0-9]*)$/;

const LETTER_OR_DIGIT_CODE = /^(?:Key[A-Z]|Digit[0-9])$/;

const MAC_MODIFIER_LABELS: Readonly<Record<string, string>> = { Mod: '⌘', Ctrl: '⌃', Alt: '⌥', Shift: '⇧' };

const MODIFIER_LABELS: Readonly<Record<string, string>> = { Mod: 'Ctrl', Ctrl: 'Ctrl', Alt: 'Alt', Shift: 'Shift' };

const KEY_LABELS: Readonly<Record<string, string>> = {
    Slash: '/',
    Backslash: '\\',
    Escape: 'Esc',
    Minus: '-',
    Equal: '=',
    Comma: ',',
    Period: '.',
    Semicolon: ';',
    Quote: "'",
    Backquote: '`',
    BracketLeft: '[',
    BracketRight: ']',
    ArrowUp: '↑',
    ArrowDown: '↓',
    ArrowLeft: '←',
    ArrowRight: '→',
};

export function chordFromEvent(event: KeyboardEvent, isMac: boolean): KeyChord | null {
    if (!event.code || MODIFIER_CODES.has(event.code)) {
        return null;
    }
    if (!isMac && event.metaKey) {
        return null;
    }
    const parts: string[] = [];
    if (isMac ? event.metaKey : event.ctrlKey) parts.push('Mod');
    if (isMac && event.ctrlKey) parts.push('Ctrl');
    if (event.altKey) parts.push('Alt');
    if (event.shiftKey && event.key !== '/') parts.push('Shift');
    parts.push(mainKeyFromEvent(event));
    return parts.join('+');
}

export function mainKeyFromEvent(event: Pick<KeyboardEvent, 'key' | 'code'>): string {
    if (/^[a-z]$/i.test(event.key)) {
        return `Key${event.key.toUpperCase()}`;
    }
    if (/^[0-9]$/.test(event.key)) {
        return `Digit${event.key}`;
    }
    if (event.key === '/') {
        return 'Slash';
    }
    return event.code;
}

export function formatChord(chord: KeyChord, isMac: boolean): string[] {
    const parts = chord.split('+');
    const code = parts.pop() ?? '';
    return [...formatKeyLabels(parts, isMac), keyLabel(code)];
}

export function formatKeyLabels(keys: readonly string[], isMac: boolean): string[] {
    const modifierLabels = isMac ? MAC_MODIFIER_LABELS : MODIFIER_LABELS;
    return keys.map((key) => modifierLabels[key] ?? key);
}

export function isEditableTarget(element: HTMLElement): boolean {
    return (
        element.matches('input,textarea,select,[contenteditable="true"]') ||
        !!element.closest('.monaco-editor, .native-edit-context')
    );
}

export function isInsideSidePanel(element: Element): boolean {
    return !!element.closest('app-node-panel-shell');
}

export function checkUserChord(chord: KeyChord): ChordRejection | null {
    const match = WELL_FORMED_CHORD.exec(chord);
    if (!match || MODIFIER_CODES.has(match[1]) || MODIFIER_TOKENS.has(match[1])) {
        return 'invalid';
    }
    const modifiers = chord.split('+').slice(0, -1);
    if (modifiers.includes('Ctrl')) {
        return 'mac-ctrl';
    }
    if (RESERVED_CHORDS.has(chord)) {
        return 'reserved';
    }
    if (modifiers.length === 0) {
        return 'bare-key';
    }
    return null;
}

function keyLabel(code: string): string {
    if (KEY_LABELS[code]) {
        return KEY_LABELS[code];
    }
    if (LETTER_OR_DIGIT_CODE.test(code)) {
        return code.replace(/^(?:Key|Digit)/, '');
    }
    return code;
}
