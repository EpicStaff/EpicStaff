import { checkUserChord, chordFromEvent, formatChord, isInsideSidePanel } from './key-chord.util';

function keydown(init: KeyboardEventInit): KeyboardEvent {
    return new KeyboardEvent('keydown', init);
}

describe('chordFromEvent', () => {
    it.each([
        ['German Ctrl+Z', { key: 'z', code: 'KeyY', ctrlKey: true }, 'Mod+KeyZ'],
        ['German Ctrl+Y', { key: 'y', code: 'KeyZ', ctrlKey: true }, 'Mod+KeyY'],
        ['French Ctrl+Z', { key: 'z', code: 'KeyW', ctrlKey: true }, 'Mod+KeyZ'],
        ['Dvorak Ctrl+S', { key: 's', code: 'Semicolon', ctrlKey: true }, 'Mod+KeyS'],
        ['Cyrillic Ctrl+F', { key: 'а', code: 'KeyF', ctrlKey: true }, 'Mod+KeyF'],
        ['Cyrillic Ctrl+Z', { key: 'я', code: 'KeyZ', ctrlKey: true }, 'Mod+KeyZ'],
        ['Shift+P', { key: 'P', code: 'KeyP', shiftKey: true }, 'Shift+KeyP'],
        ['Shift+1', { key: '!', code: 'Digit1', shiftKey: true }, 'Shift+Digit1'],
        ['Ctrl+7', { key: '7', code: 'Digit7', ctrlKey: true }, 'Mod+Digit7'],
        ['Ctrl+/', { key: '/', code: 'Slash', ctrlKey: true }, 'Mod+Slash'],
        ['German Ctrl+/ (Shift+7)', { key: '/', code: 'Digit7', ctrlKey: true, shiftKey: true }, 'Mod+Slash'],
        ['French Ctrl+/ (Shift+colon)', { key: '/', code: 'Period', ctrlKey: true, shiftKey: true }, 'Mod+Slash'],
        ['US Ctrl+Shift+/ (types ?)', { key: '?', code: 'Slash', ctrlKey: true, shiftKey: true }, 'Mod+Shift+Slash'],
    ] as const)('names the key the layout prints, else the physical key: %s', (_label, init, expected) => {
        expect(chordFromEvent(keydown(init), false)).toBe(expected);
    });

    it('falls back to the physical key for a mac Alt character', () => {
        expect(chordFromEvent(keydown({ key: 'π', code: 'KeyP', altKey: true }), true)).toBe('Alt+KeyP');
    });

    it('maps Ctrl to Mod outside mac', () => {
        expect(chordFromEvent(keydown({ code: 'KeyS', ctrlKey: true }), false)).toBe('Mod+KeyS');
    });

    it('maps Cmd to Mod on mac and keeps a physical Ctrl as its own token there', () => {
        expect(chordFromEvent(keydown({ code: 'KeyS', metaKey: true }), true)).toBe('Mod+KeyS');
        expect(chordFromEvent(keydown({ code: 'KeyS', ctrlKey: true }), true)).toBe('Ctrl+KeyS');
        expect(chordFromEvent(keydown({ code: 'KeyS', metaKey: true, ctrlKey: true }), true)).toBe('Mod+Ctrl+KeyS');
    });

    it('orders modifiers Mod, Ctrl, Alt, Shift', () => {
        expect(chordFromEvent(keydown({ code: 'KeyA', shiftKey: true, altKey: true, ctrlKey: true }), false)).toBe(
            'Mod+Alt+Shift+KeyA'
        );
        expect(
            chordFromEvent(keydown({ code: 'KeyA', shiftKey: true, altKey: true, ctrlKey: true, metaKey: true }), true)
        ).toBe('Mod+Ctrl+Alt+Shift+KeyA');
    });

    it('returns a bare key without modifiers', () => {
        expect(chordFromEvent(keydown({ code: 'Delete' }), false)).toBe('Delete');
    });

    it.each(['ShiftLeft', 'ControlRight', 'AltLeft', 'MetaLeft'])('returns null for a lone %s press', (code) => {
        expect(chordFromEvent(keydown({ code, shiftKey: true }), false)).toBeNull();
    });

    it('returns null for an event without a physical key', () => {
        expect(chordFromEvent(keydown({ code: '', key: 'a' }), false)).toBeNull();
    });

    it('returns null when the Windows key is held outside mac', () => {
        expect(chordFromEvent(keydown({ code: 'KeyS', metaKey: true, shiftKey: true }), false)).toBeNull();
    });
});

describe('formatChord', () => {
    it.each([
        ['Mod+Shift+KeyZ', true, ['⌘', '⇧', 'Z']],
        ['Mod+Shift+KeyZ', false, ['Ctrl', 'Shift', 'Z']],
        ['Ctrl+Alt+KeyA', true, ['⌃', '⌥', 'A']],
        ['Alt+Digit1', false, ['Alt', '1']],
        ['Mod+Slash', false, ['Ctrl', '/']],
        ['Escape', false, ['Esc']],
        ['Delete', false, ['Delete']],
    ] as const)('formats %s (mac: %s)', (chord, isMac, expected) => {
        expect(formatChord(chord, isMac)).toEqual(expected);
    });
});

describe('checkUserChord', () => {
    it.each([
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
        'Alt+ArrowUp',
        'Alt+ArrowDown',
    ])('rejects reserved %s', (chord) => {
        expect(checkUserChord(chord)).toBe('reserved');
    });

    it.each(['KeyA', 'Digit1', 'F2', 'Tab', 'Enter', 'Space', 'Backspace', 'ArrowUp'])(
        'rejects the bare key %s',
        (chord) => {
            expect(checkUserChord(chord)).toBe('bare-key');
        }
    );

    it.each([
        '',
        'Shift+',
        'Shift+Mod+KeyA',
        'Hyper+KeyA',
        'Shift+ShiftLeft',
        'Mod+Mod+KeyA',
        'Mod',
        'Shift',
        'Mod+Ctrl',
        'Alt+Shift',
        'keya',
        'Shift+keya',
        'Shift+1',
    ])('rejects the malformed chord "%s"', (chord) => {
        expect(checkUserChord(chord)).toBe('invalid');
    });

    it.each(['Ctrl+Shift+KeyA', 'Mod+Ctrl+KeyA', 'Ctrl+Alt+KeyA', 'Ctrl+KeyB'])(
        'rejects %s because a physical Ctrl key on a mac does not exist elsewhere',
        (chord) => {
            expect(checkUserChord(chord)).toBe('mac-ctrl');
        }
    );

    it('checks the mac Ctrl rule before the reserved rule', () => {
        expect(checkUserChord('Ctrl+KeyS')).toBe('mac-ctrl');
    });

    it.each(['Shift+KeyB', 'Alt+KeyG', 'Mod+Shift+KeyB', 'Mod+Digit1', 'Shift+F2', 'Alt+Comma', 'Mod+Alt+Shift+KeyQ'])(
        'accepts %s',
        (chord) => {
            expect(checkUserChord(chord)).toBeNull();
        }
    );
});

describe('isInsideSidePanel', () => {
    it('is true for an element inside the node side panel and false elsewhere', () => {
        const panel = document.createElement('app-node-panel-shell');
        const input = document.createElement('input');
        panel.appendChild(input);

        expect(isInsideSidePanel(input)).toBe(true);
        expect(isInsideSidePanel(document.createElement('input'))).toBe(false);
    });
});
