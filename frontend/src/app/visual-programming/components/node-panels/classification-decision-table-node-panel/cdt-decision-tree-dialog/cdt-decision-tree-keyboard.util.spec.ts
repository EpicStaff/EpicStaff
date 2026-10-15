import { CdtTreeKeyState, resolveTreeKeyAction } from './cdt-decision-tree-keyboard.util';

type KeyEvent = Parameters<typeof resolveTreeKeyAction>[0];

const IDLE: CdtTreeKeyState = {
    detailOpen: false,
    explainMenuOpen: false,
    searchOpen: false,
    searchExpanded: false,
    searchHasText: false,
    targetIsSearch: false,
};

function key(value: string, code = '', modifiers: Partial<Pick<KeyEvent, 'ctrlKey' | 'metaKey'>> = {}): KeyEvent {
    return { key: value, code, ctrlKey: false, metaKey: false, ...modifiers };
}

function ctrl(value: string, code: string): KeyEvent {
    return key(value, code, { ctrlKey: true });
}

function cmd(value: string, code: string): KeyEvent {
    return key(value, code, { metaKey: true });
}

function state(overrides: Partial<CdtTreeKeyState>): CdtTreeKeyState {
    return { ...IDLE, ...overrides };
}

describe('resolveTreeKeyAction', () => {
    describe('keys the flow page deletes the selected node on', () => {
        it.each([
            ['Delete', 'Delete'],
            ['Backspace', 'Backspace'],
        ])('shields %s from the page without cancelling it', (value, code) => {
            expect(resolveTreeKeyAction(key(value, code), IDLE)).toEqual({
                action: 'none',
                stopPropagation: true,
                preventDefault: false,
            });
        });

        it.each(['Delete', 'Backspace'])('shields %s with a modifier held too', (value) => {
            expect(resolveTreeKeyAction(ctrl(value, value), IDLE).stopPropagation).toBe(true);
        });

        it.each(['Delete', 'Backspace'])(
            'lets %s reach the search box, which the page already exempts as a text field',
            (value) => {
                expect(resolveTreeKeyAction(key(value, value), state({ targetIsSearch: true }))).toEqual({
                    action: 'none',
                    stopPropagation: false,
                    preventDefault: false,
                });
            }
        );
    });

    describe('Ctrl/Cmd+S, which the page turns into a real save request', () => {
        it.each([
            ['Ctrl', ctrl('s', 'KeyS')],
            ['Cmd', cmd('s', 'KeyS')],
            ['Ctrl+Shift', ctrl('S', 'KeyS')],
            ['Ctrl on a RU layout', ctrl('ы', 'KeyS')],
        ])('is stopped and cancelled with %s', (_label, event) => {
            expect(resolveTreeKeyAction(event, IDLE)).toEqual({
                action: 'none',
                stopPropagation: true,
                preventDefault: true,
            });
        });

        it('is stopped and cancelled even while typing in the search box', () => {
            expect(resolveTreeKeyAction(ctrl('s', 'KeyS'), state({ targetIsSearch: true }))).toEqual({
                action: 'none',
                stopPropagation: true,
                preventDefault: true,
            });
        });

        it('lets a bare s through as typing', () => {
            expect(resolveTreeKeyAction(key('s', 'KeyS'), IDLE)).toEqual({
                action: 'none',
                stopPropagation: false,
                preventDefault: false,
            });
        });
    });

    describe('the page clipboard, undo, shortcuts and node search', () => {
        it.each([
            ['copy', ctrl('c', 'KeyC')],
            ['copy (RU)', ctrl('с', 'KeyC')],
            ['paste', ctrl('v', 'KeyV')],
            ['paste (RU)', ctrl('м', 'KeyV')],
            ['undo', ctrl('z', 'KeyZ')],
            ['undo (RU)', ctrl('я', 'KeyZ')],
            ['redo with Shift', ctrl('Z', 'KeyZ')],
            ['redo', ctrl('y', 'KeyY')],
            ['redo (RU)', ctrl('н', 'KeyY')],
            ['shortcuts dialog', ctrl('/', 'Slash')],
            ['canvas node search', ctrl('f', 'KeyF')],
            ['undo with Cmd', cmd('z', 'KeyZ')],
        ])('shields %s but leaves the native behaviour alone', (_label, event) => {
            expect(resolveTreeKeyAction(event, IDLE)).toEqual({
                action: 'none',
                stopPropagation: true,
                preventDefault: false,
            });
        });

        it.each([
            ['undo', ctrl('z', 'KeyZ')],
            ['copy', ctrl('c', 'KeyC')],
            ['paste', ctrl('v', 'KeyV')],
        ])('lets %s reach the search box, where the page already ignores it', (_label, event) => {
            expect(resolveTreeKeyAction(event, state({ targetIsSearch: true })).stopPropagation).toBe(false);
        });

        it.each([
            ['canvas node search (RU)', ctrl('а', 'KeyF')],
            ['undo (German)', ctrl('z', 'KeyY')],
            ['save (Dvorak)', ctrl('s', 'Semicolon')],
            ['shortcuts dialog (RU)', ctrl('.', 'Slash')],
        ])('shields %s by the key the keymap matches', (_label, event) => {
            expect(resolveTreeKeyAction(event, IDLE).stopPropagation).toBe(true);
        });
    });

    describe('keys the page does not act on', () => {
        it.each([
            ['ArrowUp', key('ArrowUp', 'ArrowUp')],
            ['ArrowDown', key('ArrowDown', 'ArrowDown')],
            ['ArrowLeft', key('ArrowLeft', 'ArrowLeft')],
            ['ArrowRight', key('ArrowRight', 'ArrowRight')],
            ['Ctrl+ArrowLeft', ctrl('ArrowLeft', 'ArrowLeft')],
            ['Enter', key('Enter', 'Enter')],
            ['Space', key(' ', 'Space')],
            ['Tab', key('Tab', 'Tab')],
            ['a letter', key('a', 'KeyA')],
            ['Ctrl+A', ctrl('a', 'KeyA')],
            ['a lone Ctrl', ctrl('Control', 'ControlLeft')],
        ])('passes %s through untouched', (_label, event) => {
            expect(resolveTreeKeyAction(event, IDLE)).toEqual({
                action: 'none',
                stopPropagation: false,
                preventDefault: false,
            });
        });
    });

    describe('Escape', () => {
        it('closes the dialog when nothing inside it is open', () => {
            expect(resolveTreeKeyAction(key('Escape', 'Escape'), IDLE)).toEqual({
                action: 'close-dialog',
                stopPropagation: true,
                preventDefault: true,
            });
        });

        it('is stopped and cancelled from inside the search box as well', () => {
            const result = resolveTreeKeyAction(key('Escape', 'Escape'), state({ targetIsSearch: true }));

            expect(result.stopPropagation).toBe(true);
            expect(result.preventDefault).toBe(true);
        });

        it.each<[string, Partial<CdtTreeKeyState>, string]>([
            [
                'the model picker over everything else',
                {
                    explainMenuOpen: true,
                    searchOpen: true,
                    searchExpanded: true,
                    searchHasText: true,
                    targetIsSearch: true,
                    detailOpen: true,
                },
                'close-explain-menu',
            ],
            [
                'the search dropdown before the text under the caret',
                { searchOpen: true, searchExpanded: true, searchHasText: true, targetIsSearch: true, detailOpen: true },
                'close-search',
            ],
            [
                'the text in the focused search box before the box',
                { searchExpanded: true, searchHasText: true, targetIsSearch: true, detailOpen: true },
                'clear-search',
            ],
            [
                'the expanded search box before the detail window',
                { searchExpanded: true, detailOpen: true },
                'collapse-search',
            ],
            [
                'the box, not its text, when focus is elsewhere',
                { searchExpanded: true, searchHasText: true, targetIsSearch: false },
                'collapse-search',
            ],
            ['the detail window before the dialog', { detailOpen: true }, 'close-detail'],
        ])('dismisses %s', (_label, overrides, expected) => {
            const result = resolveTreeKeyAction(key('Escape', 'Escape'), state(overrides));

            expect(result.action).toBe(expected);
            expect(result.stopPropagation).toBe(true);
            expect(result.preventDefault).toBe(true);
        });

        it('acts on no other key, whatever is open', () => {
            const everythingOpen = state({
                explainMenuOpen: true,
                searchOpen: true,
                searchExpanded: true,
                searchHasText: true,
                detailOpen: true,
            });

            expect(resolveTreeKeyAction(key('Delete', 'Delete'), everythingOpen).action).toBe('none');
            expect(resolveTreeKeyAction(ctrl('s', 'KeyS'), everythingOpen).action).toBe('none');
            expect(resolveTreeKeyAction(key('Enter', 'Enter'), everythingOpen).action).toBe('none');
        });
    });
});
