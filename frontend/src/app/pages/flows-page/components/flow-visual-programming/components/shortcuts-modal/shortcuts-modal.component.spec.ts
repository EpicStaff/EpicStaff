import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { GetMeResponse, ShortcutSettings } from '@shared/models';

import { GetGraphLightRequest } from '../../../../../../features/flows/models/graph.model';
import { ProfileService } from '../../../../../../services/auth/profile.service';
import { ConfigService } from '../../../../../../services/config';
import { ToastMessage, ToastService } from '../../../../../../services/notifications';
import { KeymapService, PLATFORM_IS_MAC } from '../../../../../../visual-programming/services/keymap.service';
import { ShortcutsModalComponent } from './shortcuts-modal.component';

const PROFILE_URL = '/api/profile/';

const BASE_USER: GetMeResponse = {
    id: 7,
    email: 'jane@example.com',
    display_name: 'Jane Doe',
    is_superadmin: false,
    is_active: true,
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
    memberships: [],
    active_organization_id: 3,
    active_permissions: null,
    avatar_url: null,
    custom_shortcuts: { custom: [] },
};

const NODE_LABELS_AND_LETTERS: readonly (readonly [string, string])[] = [
    ['Python Code Node', 'P'],
    ['Classification Decision Table', 'C'],
    ['Knowledge Retriever', 'K'],
    ['Task Node', 'T'],
    ['Agent Node', 'A'],
    ['Key-Value', 'V'],
    ['Note', 'N'],
    ['Decision Table', 'D'],
    ['File Extractor', 'F'],
    ['Schedule Trigger', 'S'],
    ['Webhook Trigger', 'W'],
    ['Telegram Trigger', 'G'],
    ['Audio to text', 'U'],
    ['End', 'E'],
];

const BASE_SECTIONS = ['Editing', 'Navigating', 'Selection', 'Zoom', 'Nodes'];

interface RenderedRow {
    label: string;
    chords: string[][];
}

interface RenderedCustomRow {
    label: string;
    keys: string;
}

type CustomRow = ShortcutSettings['custom'][number];

class ResizeObserverStub {
    observe(): void {}
    unobserve(): void {}
    disconnect(): void {}
}

describe('ShortcutsModalComponent', () => {
    let fixture: ComponentFixture<ShortcutsModalComponent>;
    let httpMock: HttpTestingController;
    let toasts: ToastMessage[];
    let closedCount: number;

    function setUp(isMac = false): void {
        vi.stubGlobal('ResizeObserver', ResizeObserverStub);
        TestBed.configureTestingModule({
            imports: [ShortcutsModalComponent],
            providers: [
                provideHttpClient(),
                provideHttpClientTesting(),
                { provide: ConfigService, useValue: { apiUrl: '/api/' } as unknown as ConfigService },
                { provide: PLATFORM_IS_MAC, useValue: isMac },
            ],
        });
        httpMock = TestBed.inject(HttpTestingController);
        toasts = [];
        TestBed.inject(ToastService).toasts$.subscribe((current) => (toasts = current));
    }

    function loadUser(custom: CustomRow[]): void {
        TestBed.inject(ProfileService).getCurrentUser().subscribe();
        httpMock.expectOne({ method: 'GET', url: PROFILE_URL }).flush({ ...BASE_USER, custom_shortcuts: { custom } });
    }

    function openModal(): void {
        fixture = TestBed.createComponent(ShortcutsModalComponent);
        fixture.componentRef.setInput('open', true);
        fixture.componentRef.setInput('pos', { top: 10, left: 10 });
        closedCount = 0;
        fixture.componentInstance.closed.subscribe(() => (closedCount += 1));
        render();
    }

    function render(): void {
        fixture.detectChanges();
        TestBed.tick();
    }

    function nextPatch(): { body: unknown; succeed: () => void; fail: () => void } {
        const request = httpMock.expectOne({ method: 'PATCH', url: PROFILE_URL });
        const body = request.request.body as { custom_shortcuts: ShortcutSettings };
        return {
            body,
            succeed: () => {
                request.flush({ ...BASE_USER, custom_shortcuts: body.custom_shortcuts });
                render();
            },
            fail: () => {
                request.flush({ detail: 'boom' }, { status: 500, statusText: 'Server Error' });
                render();
            },
        };
    }

    function text(element: Element): string {
        return (element.textContent ?? '').replace(/\s+/g, ' ').trim();
    }

    function root(): HTMLElement {
        return fixture.nativeElement;
    }

    function sectionTitles(): string[] {
        return Array.from(root().querySelectorAll('.shortcuts__card-title'), text);
    }

    function cardOf(sectionTitle: string): Element {
        const card = Array.from(root().querySelectorAll('.shortcuts__card') as NodeListOf<Element>).find(
            (candidate) => text(candidate.querySelector('.shortcuts__card-title')!) === sectionTitle
        );
        if (!card) throw new Error(`No "${sectionTitle}" section rendered`);
        return card;
    }

    function rowsOf(sectionTitle: string): RenderedRow[] {
        return rowElementsOf(sectionTitle).map(readRow);
    }

    function rowElementsOf(sectionTitle: string): Element[] {
        return Array.from(cardOf(sectionTitle).querySelectorAll('.shortcuts__row'));
    }

    function readRow(row: Element): RenderedRow {
        const chords: string[][] = [];
        row.querySelector('.shortcuts__keys')!.childNodes.forEach((node) => {
            if (!(node instanceof Element)) return;
            if (node.classList.contains('shortcuts__or')) {
                chords.push([]);
            } else if (node.classList.contains('shortcuts__key')) {
                if (chords.length === 0) chords.push([]);
                chords[chords.length - 1].push(text(node));
            }
        });
        return { label: text(row.querySelector('.shortcuts__label')!), chords };
    }

    function nodeRow(label: string): string {
        const row = rowElementsOf('Nodes').find((candidate) => readRow(candidate).label === label)!;
        return text(row.querySelector('.shortcuts__keys')!);
    }

    function customRows(): RenderedCustomRow[] {
        return rowElementsOf('Custom').map((row) => ({
            label: text(row.querySelector('.shortcuts__label')!),
            keys: text(row.querySelector('.shortcuts__keys')!),
        }));
    }

    function buttonNamed(name: string, container: Element = root()): HTMLButtonElement {
        const button = Array.from(container.querySelectorAll('button')).find(
            (candidate) => (candidate.getAttribute('aria-label') ?? text(candidate)) === name
        );
        if (!button) throw new Error(`No "${name}" button rendered`);
        return button;
    }

    function hasButton(name: string, container: Element = root()): boolean {
        return Array.from(container.querySelectorAll('button')).some(
            (candidate) => (candidate.getAttribute('aria-label') ?? text(candidate)) === name
        );
    }

    function click(button: HTMLElement): void {
        button.click();
        render();
    }

    function editor(): HTMLElement | null {
        return root().querySelector('app-shortcut-editor');
    }

    function actionPicker(): HTMLInputElement {
        return editor()!.querySelector('input[role="combobox"]')!;
    }

    function keysBox(): HTMLButtonElement {
        return editor()!.querySelector('.shortcut-editor__recorder')!;
    }

    function saveButton(): HTMLButtonElement {
        return buttonNamed('Save', editor()!);
    }

    function feedback(): string {
        const message = editor()!.querySelector('.shortcut-editor__feedback');
        return message ? text(message) : '';
    }

    function pickAction(label: string): void {
        const input = actionPicker();
        input.focus();
        input.value = label.slice(0, 4);
        input.dispatchEvent(new Event('input'));
        render();
        const option = Array.from(editor()!.querySelectorAll('[role="option"]')).find(
            (candidate) => text(candidate) === label
        );
        if (!option) throw new Error(`No "${label}" option in the picker`);
        (option as HTMLElement).click();
        render();
    }

    function press(target: HTMLElement, init: KeyboardEventInit): KeyboardEvent {
        const event = new KeyboardEvent('keydown', { bubbles: true, cancelable: true, ...init });
        target.dispatchEvent(event);
        render();
        return event;
    }

    function record(init: KeyboardEventInit): KeyboardEvent {
        click(keysBox());
        return press(keysBox(), init);
    }

    function startAdding(): void {
        click(buttonNamed('Add shortcut'));
    }

    afterEach(() => {
        try {
            httpMock.verify();
        } finally {
            TestBed.resetTestingModule();
            vi.unstubAllGlobals();
        }
    });

    it('shows the sections in order, Nodes last', () => {
        setUp();
        openModal();

        expect(sectionTitles()).toEqual(BASE_SECTIONS);
    });

    it('keeps the same height when minimized', () => {
        setUp();
        openModal();
        const modal = (): HTMLElement => root().querySelector('.shortcuts__modal')!;
        const height = (): string => modal().style.getPropertyValue('--shortcuts-modal-height');
        const wideHeight = height();

        click(root().querySelector('.shortcuts__size-btn')!);

        expect(modal().classList).toContain('shortcuts__modal--compact');
        expect(wideHeight).toBe('666px');
        expect(height()).toBe('666px');
    });

    it.each([
        ['Windows/Linux', false, 'Shift'],
        ['macOS', true, '⇧'],
    ])('lists every node with its Shift+letter key on %s', (_platform, isMac, shift) => {
        setUp(isMac);
        openModal();

        expect(rowsOf('Nodes')).toEqual(
            NODE_LABELS_AND_LETTERS.map(([label, letter]) => ({ label, chords: [[shift, letter]] }))
        );
    });

    it.each([
        [
            'Windows/Linux',
            false,
            [
                { label: 'Save', chords: [['Ctrl', 'S']] },
                { label: 'Undo', chords: [['Ctrl', 'Z']] },
                {
                    label: 'Redo',
                    chords: [
                        ['Ctrl', 'Shift', 'Z'],
                        ['Ctrl', 'Y'],
                    ],
                },
            ],
        ],
        [
            'macOS',
            true,
            [
                { label: 'Save', chords: [['⌘', 'S']] },
                { label: 'Undo', chords: [['⌘', 'Z']] },
                {
                    label: 'Redo',
                    chords: [
                        ['⌘', '⇧', 'Z'],
                        ['⌘', 'Y'],
                    ],
                },
            ],
        ],
    ])('shows save, undo and both redo chords in one row with the %s modifier', (_platform, isMac, expected) => {
        setUp(isMac);
        openModal();

        expect(rowsOf('Editing').filter((row) => ['Save', 'Undo', 'Redo'].includes(row.label))).toEqual(expected);
    });

    it('shows each action once, with its alternative keys separated by "or"', () => {
        setUp();
        openModal();

        const deleteRows = rowsOf('Editing').filter((row) => row.label === 'Delete');
        expect(deleteRows).toEqual([{ label: 'Delete', chords: [['Delete'], ['Backspace']] }]);
        const deleteRow = rowElementsOf('Editing').find((row) => readRow(row).label === 'Delete')!;
        expect(Array.from(deleteRow.querySelectorAll('.shortcuts__or'), text)).toEqual(['or']);
    });

    it('shows the navigating actions with one key each', () => {
        setUp();
        openModal();

        expect(rowsOf('Navigating')).toEqual([
            { label: 'Node search', chords: [['Ctrl', 'F']] },
            { label: 'Keyboard shortcuts', chords: [['Ctrl', '/']] },
            { label: 'Open node create menu', chords: [['Right click']] },
        ]);
    });

    it.each([
        ['Windows/Linux', false, [['Ctrl', 'click']], [['Shift', 'drag']]],
        ['macOS', true, [['⌘', 'click']], [['⇧', 'drag']]],
    ])('shows the selection gestures with the %s modifier', (_platform, isMac, toggleChords, zoneChords) => {
        setUp(isMac);
        openModal();

        expect(rowsOf('Selection')).toEqual([
            { label: 'Add/remove selection', chords: toggleChords },
            { label: 'Zone selection', chords: zoneChords },
        ]);
    });

    it('shows the zoom gestures', () => {
        setUp();
        openModal();

        expect(rowsOf('Zoom')).toEqual([
            { label: 'Zoom in', chords: [['Mouse wheel up']] },
            { label: 'Zoom out', chords: [['Mouse wheel down']] },
        ]);
    });

    describe('base rows', () => {
        it('show only the built-in key; the extra key is listed under Custom', () => {
            setUp();
            loadUser([{ action: 'node.python', keys: 'Shift+KeyB' }]);
            openModal();

            expect(rowsOf('Nodes')[0]).toEqual({ label: 'Python Code Node', chords: [['Shift', 'P']] });
            expect(customRows()).toEqual([{ label: 'Python Code Node', keys: 'Shift B' }]);
        });

        it('say Not set for a node whose key a custom shortcut took', () => {
            setUp();
            loadUser([{ action: 'node.agent', keys: 'Shift+KeyP' }]);
            openModal();

            expect(nodeRow('Python Code Node')).toBe('Not set');
            expect(nodeRow('Agent Node')).toBe('Shift A');
        });

        it('have no edit, delete or reset controls', () => {
            setUp();
            loadUser([{ action: 'node.agent', keys: 'Shift+KeyP' }]);
            openModal();

            for (const title of BASE_SECTIONS) {
                expect(cardOf(title).querySelectorAll('button')).toHaveLength(0);
            }
        });
    });

    describe('custom section', () => {
        it('is hidden while the user has no custom shortcuts', () => {
            setUp();
            openModal();

            expect(sectionTitles()).toEqual(BASE_SECTIONS);
            expect(hasButton('Add shortcut')).toBe(true);
        });

        it('lists each custom shortcut with its keys, or Not set, after Nodes', () => {
            setUp();
            loadUser([
                { action: 'node.agent', keys: 'Alt+KeyB' },
                { action: 'editing.save', keys: null },
            ]);
            openModal();

            expect(sectionTitles()).toEqual([...BASE_SECTIONS, 'Custom']);
            expect(customRows()).toEqual([
                { label: 'Agent Node', keys: 'Alt B' },
                { label: 'Save', keys: 'Not set' },
            ]);
        });

        it('deletes a row and saves the list without it', () => {
            setUp();
            loadUser([
                { action: 'node.agent', keys: 'Shift+KeyP' },
                { action: 'node.task', keys: 'Alt+KeyK' },
            ]);
            openModal();

            click(buttonNamed('Delete Agent Node shortcut'));

            expect(customRows()).toEqual([{ label: 'Task Node', keys: 'Alt K' }]);
            expect(nodeRow('Python Code Node')).toBe('Shift P');
            const patch = nextPatch();
            expect(patch.body).toEqual({ custom_shortcuts: { custom: [{ action: 'node.task', keys: 'Alt+KeyK' }] } });
            patch.succeed();
            expect(document.activeElement).toBe(buttonNamed('Add shortcut'));
        });
    });

    describe('keys pressed in the popover', () => {
        it('do not reach the canvas', () => {
            setUp();
            const undo = vi.fn();
            const deleteNodes = vi.fn();
            const keymap = TestBed.inject(KeymapService);
            keymap.register('editing.undo', undo);
            keymap.register('editing.delete', deleteNodes);
            loadUser([{ action: 'node.agent', keys: 'Alt+KeyB' }]);
            openModal();
            click(buttonNamed('Delete Agent Node shortcut'));
            nextPatch().succeed();
            const focused = document.activeElement as HTMLElement;

            press(focused, { key: 'z', code: 'KeyZ', ctrlKey: true });
            press(focused, { key: 'Delete', code: 'Delete' });

            expect(focused).toBe(buttonNamed('Add shortcut'));
            expect(undo).not.toHaveBeenCalled();
            expect(deleteNodes).not.toHaveBeenCalled();
            expect(closedCount).toBe(0);
        });

        it('Esc closes the popover', () => {
            setUp();
            openModal();

            press(buttonNamed('Add shortcut'), { key: 'Escape', code: 'Escape' });

            expect(closedCount).toBe(1);
        });

        it('still lets the keyboard shortcuts key toggle the popover', () => {
            setUp();
            const toggleShortcuts = vi.fn();
            TestBed.inject(KeymapService).register('navigating.shortcuts', toggleShortcuts);
            openModal();

            press(buttonNamed('Add shortcut'), { key: '/', code: 'Slash', ctrlKey: true });

            expect(toggleShortcuts).toHaveBeenCalledOnce();
        });
    });

    describe('adding a shortcut', () => {
        it('moves focus into the action picker', () => {
            setUp();
            openModal();

            startAdding();

            expect(document.activeElement).toBe(actionPicker());
        });

        it('takes a node key with a warning, saves it and leaves that node Not set', () => {
            setUp();
            const pythonNode = vi.fn();
            TestBed.inject(KeymapService).register('node.python', pythonNode);
            openModal();

            startAdding();
            pickAction('Agent Node');
            const recorded = record({ key: 'P', code: 'KeyP', shiftKey: true });

            expect(pythonNode).not.toHaveBeenCalled();
            expect(recorded.defaultPrevented).toBe(true);
            expect(text(keysBox())).toContain('Shift+P');
            expect(feedback()).toBe(
                "Shift+P is Python Code Node's key — saving moves it here; Python Code Node will have no key"
            );
            expect(saveButton().disabled).toBe(false);

            click(saveButton());

            expect(editor()).toBeNull();
            expect(customRows()).toEqual([{ label: 'Agent Node', keys: 'Shift P' }]);
            expect(nodeRow('Python Code Node')).toBe('Not set');
            const patch = nextPatch();
            expect(patch.body).toEqual({
                custom_shortcuts: { custom: [{ action: 'node.agent', keys: 'Shift+KeyP' }] },
            });
            patch.succeed();
        });

        it('records the physical key on a Ukrainian layout', () => {
            setUp();
            openModal();

            startAdding();
            pickAction('Agent Node');
            record({ key: 'Л', code: 'KeyK', altKey: true, shiftKey: true });

            expect(text(keysBox())).toContain('Alt+Shift+K');
        });

        it('ignores a lone modifier press while recording', () => {
            setUp();
            openModal();

            startAdding();
            pickAction('Agent Node');
            record({ key: 'Shift', code: 'ShiftLeft', shiftKey: true });
            press(keysBox(), { key: 'B', code: 'KeyB', shiftKey: true });

            expect(text(keysBox())).toContain('Shift+B');
        });

        it('saves on Enter in the keys box once Save is enabled', () => {
            setUp();
            openModal();

            startAdding();
            record({ key: 'm', code: 'KeyM', altKey: true });
            press(keysBox(), { key: 'Enter', code: 'Enter' });
            expect(editor()).not.toBeNull();

            pickAction('Task Node');
            press(keysBox(), { key: 'Enter', code: 'Enter' });

            expect(editor()).toBeNull();
            expect(customRows()).toEqual([{ label: 'Task Node', keys: 'Alt M' }]);
            nextPatch().succeed();
        });

        it.each([
            [
                'a reserved key',
                false,
                [],
                'Agent Node',
                { key: 's', code: 'KeyS', ctrlKey: true },
                'Ctrl+S is reserved',
            ],
            [
                'a key without a modifier',
                false,
                [],
                'Agent Node',
                { key: 'q', code: 'KeyQ' },
                'Add a modifier key (Ctrl, Alt or Shift)',
            ],
            [
                'a key without a modifier on a Mac',
                true,
                [],
                'Agent Node',
                { key: 'q', code: 'KeyQ' },
                'Add a modifier key (⌘, ⌥ or ⇧)',
            ],
            [
                'a key another custom shortcut has',
                false,
                [{ action: 'node.task', keys: 'Alt+KeyK' }],
                'Agent Node',
                { key: 'k', code: 'KeyK', altKey: true },
                'Already used by your Task Node shortcut',
            ],
            [
                'the action own built-in key',
                false,
                [],
                'Python Code Node',
                { key: 'P', code: 'KeyP', shiftKey: true },
                "Shift+P is already Python Code Node's key",
            ],
            [
                'a physical Ctrl key on a Mac',
                true,
                [],
                'Agent Node',
                { key: 'k', code: 'KeyK', ctrlKey: true },
                'Use ⌘, ⌥ or ⇧ instead of Ctrl',
            ],
        ] as const)('refuses %s and keeps Save disabled', (_case, isMac, stored, action, keys, message) => {
            setUp(isMac);
            loadUser([...stored]);
            openModal();

            startAdding();
            pickAction(action);
            record(keys);

            expect(feedback()).toBe(message);
            expect(saveButton().disabled).toBe(true);
            press(actionPicker(), { key: 'Enter', code: 'Enter' });
            expect(editor()).not.toBeNull();
        });

        it('Esc in the picker closes its list, then the editor, and focus goes back to Add shortcut', () => {
            setUp();
            openModal();

            startAdding();
            press(actionPicker(), { key: 'Escape', code: 'Escape' });

            expect(editor()!.querySelector('[role="listbox"]')).toBeNull();
            expect(editor()).not.toBeNull();

            press(actionPicker(), { key: 'Escape', code: 'Escape' });

            expect(editor()).toBeNull();
            expect(document.activeElement).toBe(buttonNamed('Add shortcut'));
            expect(closedCount).toBe(0);
        });

        it('picks an action with the arrow keys and Enter', () => {
            setUp();
            openModal();

            startAdding();
            press(actionPicker(), { key: 'ArrowDown', code: 'ArrowDown' });
            press(actionPicker(), { key: 'Enter', code: 'Enter' });

            expect(actionPicker().value).toBe('Classification Decision Table');
            expect(editor()!.querySelector('[role="listbox"]')).toBeNull();
            expect(document.activeElement).toBe(keysBox());
        });

        it.each([
            [99, ''],
            [100, 'You can have up to 100 custom shortcuts'],
        ])('with %i custom shortcuts saved, says "%s" about one more', (count, message) => {
            setUp();
            loadUser(Array.from({ length: count }, () => ({ action: 'node.agent', keys: null })));
            openModal();

            startAdding();
            pickAction('Task Node');
            record({ key: 'm', code: 'KeyM', altKey: true });

            expect(feedback()).toBe(message);
            expect(saveButton().disabled).toBe(message !== '');
        });

        it('keeps Save disabled until an action is picked', () => {
            setUp();
            openModal();

            startAdding();
            record({ key: 'B', code: 'KeyB', altKey: true });

            expect(saveButton().disabled).toBe(true);
        });
    });

    describe('editing a shortcut', () => {
        it('opens pre-filled and saves the new action and key in place', () => {
            setUp();
            loadUser([
                { action: 'node.agent', keys: 'Alt+KeyB' },
                { action: 'editing.save', keys: 'Alt+KeyS' },
            ]);
            openModal();

            click(buttonNamed('Edit Agent Node shortcut'));

            expect(document.activeElement).toBe(actionPicker());
            expect(actionPicker().value).toBe('Agent Node');
            expect(text(keysBox())).toContain('Alt+B');

            pickAction('Task Node');
            record({ key: 'm', code: 'KeyM', altKey: true });
            click(saveButton());

            expect(customRows()).toEqual([
                { label: 'Task Node', keys: 'Alt M' },
                { label: 'Save', keys: 'Alt S' },
            ]);
            const patch = nextPatch();
            expect(patch.body).toEqual({
                custom_shortcuts: {
                    custom: [
                        { action: 'node.task', keys: 'Alt+KeyM' },
                        { action: 'editing.save', keys: 'Alt+KeyS' },
                    ],
                },
            });
            patch.succeed();
        });

        it('can clear the key and save the row without one', () => {
            setUp();
            loadUser([{ action: 'node.agent', keys: 'Alt+KeyB' }]);
            openModal();

            click(buttonNamed('Edit Agent Node shortcut'));
            click(buttonNamed('Clear keys', editor()!));

            expect(document.activeElement).toBe(keysBox());
            expect(text(keysBox())).toContain('Press keys');

            keysBox().blur();
            render();
            click(saveButton());

            expect(customRows()).toEqual([{ label: 'Agent Node', keys: 'Not set' }]);
            const patch = nextPatch();
            expect(patch.body).toEqual({ custom_shortcuts: { custom: [{ action: 'node.agent', keys: null }] } });
            patch.succeed();
        });

        it('Esc cancels recording, then closes the editor, and only a further Esc closes the popover', () => {
            setUp();
            const editorEscape = vi.fn();
            TestBed.inject(KeymapService).register('editing.escape', editorEscape, { allowInEditable: true });
            loadUser([{ action: 'node.agent', keys: 'Alt+KeyB' }]);
            openModal();

            click(buttonNamed('Edit Agent Node shortcut'));
            click(keysBox());
            expect(text(keysBox())).toContain('Press keys');

            press(keysBox(), { key: 'Escape', code: 'Escape' });

            expect(editor()).not.toBeNull();
            expect(text(keysBox())).toContain('Alt+B');

            press(keysBox(), { key: 'Escape', code: 'Escape' });

            expect(editor()).toBeNull();
            expect(customRows()).toEqual([{ label: 'Agent Node', keys: 'Alt B' }]);
            expect(document.activeElement).toBe(buttonNamed('Edit Agent Node shortcut'));
            expect(root().querySelector('.shortcuts__modal')).not.toBeNull();
            expect(closedCount).toBe(0);
            expect(editorEscape).not.toHaveBeenCalled();

            press(document.activeElement as HTMLElement, { key: 'Escape', code: 'Escape' });

            expect(closedCount).toBe(1);
            expect(editorEscape).not.toHaveBeenCalled();
        });

        it('keeps the picked action when the Action field is clicked and Enter pressed', () => {
            setUp();
            loadUser([{ action: 'editing.save', keys: 'Alt+KeyS' }]);
            openModal();

            click(buttonNamed('Edit Save shortcut'));
            click(actionPicker());
            press(actionPicker(), { key: 'Enter', code: 'Enter' });

            expect(actionPicker().value).toBe('Save');
            expect(editor()!.querySelector('[role="listbox"]')).toBeNull();
        });

        it('closes, rolls back and tells the user when the save fails and the row is gone', () => {
            setUp();
            loadUser([{ action: 'node.agent', keys: 'Alt+KeyB' }]);
            openModal();

            click(buttonNamed('Edit Agent Node shortcut'));
            record({ key: 'm', code: 'KeyM', altKey: true });
            click(saveButton());
            click(buttonNamed('Edit Agent Node shortcut'));
            expect(editor()).not.toBeNull();

            nextPatch().fail();

            expect(editor()).toBeNull();
            expect(document.activeElement).toBe(buttonNamed('Add shortcut'));
            expect(customRows()).toEqual([{ label: 'Agent Node', keys: 'Alt B' }]);
            expect(toasts.map((toast) => toast.message)).toEqual(['Could not save shortcut']);
        });
    });

    describe('reset to defaults', () => {
        it('is hidden while no custom shortcut holds a node key', () => {
            setUp();
            loadUser([{ action: 'node.agent', keys: 'Alt+KeyB' }]);
            openModal();

            expect(hasButton('Reset to defaults')).toBe(false);
        });

        it('says how many shortcuts lose their keys, then gives the nodes their keys back', () => {
            setUp();
            loadUser([
                { action: 'node.agent', keys: 'Shift+KeyP' },
                { action: 'node.task', keys: 'Shift+KeyA' },
                { action: 'editing.save', keys: 'Alt+KeyS' },
            ]);
            openModal();

            click(buttonNamed('Reset to defaults'));
            const dialog = document.querySelector('app-confirmation-dialog')!;
            expect(text(dialog.querySelector('.dialog-message')!)).toBe(
                '2 custom shortcuts will lose their keys. Every node gets its own key back.'
            );

            click(buttonNamed('Reset', dialog));

            expect(nodeRow('Python Code Node')).toBe('Shift P');
            expect(nodeRow('Agent Node')).toBe('Shift A');
            expect(customRows()).toEqual([
                { label: 'Agent Node', keys: 'Not set' },
                { label: 'Task Node', keys: 'Not set' },
                { label: 'Save', keys: 'Alt S' },
            ]);
            expect(hasButton('Reset to defaults')).toBe(false);
            const patch = nextPatch();
            expect(patch.body).toEqual({
                custom_shortcuts: {
                    custom: [
                        { action: 'node.agent', keys: null },
                        { action: 'node.task', keys: null },
                        { action: 'editing.save', keys: 'Alt+KeyS' },
                    ],
                },
            });
            patch.succeed();
        });

        it('changes nothing when the confirmation is cancelled', () => {
            setUp();
            loadUser([{ action: 'node.agent', keys: 'Shift+KeyP' }]);
            openModal();

            click(buttonNamed('Reset to defaults'));
            const dialog = document.querySelector('app-confirmation-dialog')!;
            expect(text(dialog.querySelector('.dialog-message')!)).toBe(
                '1 custom shortcut will lose its key. Every node gets its own key back.'
            );
            click(buttonNamed('Cancel', dialog));

            expect(customRows()).toEqual([{ label: 'Agent Node', keys: 'Shift P' }]);
            expect(nodeRow('Python Code Node')).toBe('Not set');
        });
    });

    describe('Subgraph shortcuts', () => {
        const THIS_FLOW: GetGraphLightRequest = { id: 1, uuid: 'uuid-1', name: 'Onboarding', description: '' };
        const FLOWS: GetGraphLightRequest[] = [
            THIS_FLOW,
            { id: 12, uuid: 'uuid-12', name: 'Billing', description: '' },
            { id: 34, uuid: 'uuid-34', name: 'Support', description: '' },
        ];

        function openModalWithFlows(flows: GetGraphLightRequest[] = FLOWS): void {
            fixture = TestBed.createComponent(ShortcutsModalComponent);
            fixture.componentRef.setInput('open', true);
            fixture.componentRef.setInput('pos', { top: 10, left: 10 });
            fixture.componentRef.setInput('flows', flows);
            fixture.componentRef.setInput('currentFlowId', THIS_FLOW.id);
            closedCount = 0;
            fixture.componentInstance.closed.subscribe(() => (closedCount += 1));
            render();
        }

        function flowPicker(): HTMLInputElement | null {
            const pickers = editor()!.querySelectorAll<HTMLInputElement>('input[role="combobox"]');
            return pickers.length > 1 ? pickers[1] : null;
        }

        function pickFlow(name: string): void {
            const input = flowPicker()!;
            input.focus();
            input.value = name.slice(0, 3);
            input.dispatchEvent(new Event('input'));
            render();
            const option = Array.from(input.parentElement!.querySelectorAll('[role="option"]')).find(
                (candidate) => text(candidate) === name
            );
            if (!option) throw new Error(`No "${name}" flow in the picker`);
            (option as HTMLElement).click();
            render();
        }

        function customLabel(index: number): Element {
            return rowElementsOf('Custom')[index].querySelector('.shortcuts__label')!;
        }

        it('is not listed among the nodes with built-in keys', () => {
            setUp();
            openModalWithFlows();

            expect(rowsOf('Nodes').map((row) => row.label)).not.toContain('Subgraph');
        });

        it('asks for a flow only once Subgraph is picked', () => {
            setUp();
            openModalWithFlows();

            startAdding();
            pickAction('Agent Node');
            expect(flowPicker()).toBeNull();

            pickAction('Subgraph');
            expect(flowPicker()).not.toBeNull();
        });

        it('keeps Save disabled until a flow is picked, then saves the row with its flow', () => {
            setUp();
            openModalWithFlows();

            startAdding();
            pickAction('Subgraph');
            expect(saveButton().disabled).toBe(true);
            press(flowPicker()!, { key: 'Enter', code: 'Enter' });
            expect(editor()).not.toBeNull();
            record({ key: '1', code: 'Digit1', altKey: true });
            expect(saveButton().disabled).toBe(true);

            pickFlow('Support');
            expect(saveButton().disabled).toBe(false);
            click(saveButton());

            expect(customRows()).toEqual([{ label: 'Subgraph: Support', keys: 'Alt 1' }]);
            const patch = nextPatch();
            expect(patch.body).toEqual({
                custom_shortcuts: { custom: [{ action: 'node.subgraph', keys: 'Alt+Digit1', params: { flowId: 34 } }] },
            });
            patch.succeed();
        });

        function flowOptions(query: string): string[] {
            const input = flowPicker()!;
            input.focus();
            input.value = query;
            input.dispatchEvent(new Event('input'));
            render();
            return Array.from(input.parentElement!.querySelectorAll('[role="option"]'), text);
        }

        function actionOptions(query: string): string[] {
            const input = actionPicker();
            input.focus();
            input.value = query;
            input.dispatchEvent(new Event('input'));
            render();
            return Array.from(editor()!.querySelectorAll('[role="option"]'), text);
        }

        it('lists the other flows, not the one being edited, and filters them by name', () => {
            setUp();
            openModalWithFlows();

            startAdding();
            pickAction('Subgraph');

            expect(flowOptions('')).toEqual(['Billing', 'Support']);
            expect(flowOptions('sup')).toEqual(['Support']);
        });

        it('names a row for the flow being edited as this flow, muted, and lets its edit keep or change it', () => {
            setUp();
            loadUser([{ action: 'node.subgraph', keys: 'Alt+Digit1', params: { flowId: THIS_FLOW.id } }]);
            openModalWithFlows();

            expect(customRows()).toEqual([{ label: 'Subgraph: Onboarding (this flow)', keys: 'Alt 1' }]);
            expect(customLabel(0).classList).toContain('shortcuts__label--muted');

            click(buttonNamed('Edit Subgraph: Onboarding (this flow) shortcut'));
            expect(flowPicker()!.value).toBe('Onboarding (this flow)');
            expect(saveButton().disabled).toBe(false);

            pickFlow('Billing');
            click(saveButton());

            expect(customRows()).toEqual([{ label: 'Subgraph: Billing', keys: 'Alt 1' }]);
            expect(nextPatch().body).toEqual({
                custom_shortcuts: { custom: [{ action: 'node.subgraph', keys: 'Alt+Digit1', params: { flowId: 12 } }] },
            });
        });

        it('does not offer Subgraph when no other flow can be picked, but keeps and edits an existing row', () => {
            setUp();
            loadUser([{ action: 'node.subgraph', keys: 'Alt+Digit1', params: { flowId: 99 } }]);
            openModalWithFlows([THIS_FLOW]);

            startAdding();
            expect(actionOptions('Sub')).toEqual([]);
            click(buttonNamed('Cancel', editor()!));

            expect(customRows()).toEqual([{ label: 'Subgraph: Flow not available', keys: 'Alt 1' }]);
            click(buttonNamed('Edit Subgraph: Flow not available shortcut'));
            expect(actionPicker().value).toBe('Subgraph');
        });

        it('says a row whose flow is gone is not available, muted, and still edits and deletes it', () => {
            setUp();
            loadUser([
                { action: 'node.subgraph', keys: 'Alt+Digit1', params: { flowId: 99 } },
                { action: 'node.subgraph', keys: 'Alt+Digit2', params: { flowId: 12 } },
            ]);
            openModalWithFlows();

            expect(customRows()).toEqual([
                { label: 'Subgraph: Flow not available', keys: 'Alt 1' },
                { label: 'Subgraph: Billing', keys: 'Alt 2' },
            ]);
            expect(customLabel(0).classList).toContain('shortcuts__label--muted');
            expect(customLabel(1).classList).not.toContain('shortcuts__label--muted');

            click(buttonNamed('Edit Subgraph: Flow not available shortcut'));
            expect(flowPicker()!.value).toBe('');
            expect(saveButton().disabled).toBe(true);
            pickFlow('Support');
            click(saveButton());
            expect(customRows()[0]).toEqual({ label: 'Subgraph: Support', keys: 'Alt 1' });
            nextPatch().succeed();

            click(buttonNamed('Delete Subgraph: Billing shortcut'));
            expect(nextPatch().body).toEqual({
                custom_shortcuts: { custom: [{ action: 'node.subgraph', keys: 'Alt+Digit1', params: { flowId: 34 } }] },
            });
        });

        it('opens an edited row with its flow filled in and moves it to another flow', () => {
            setUp();
            loadUser([{ action: 'node.subgraph', keys: 'Alt+Digit1', params: { flowId: 34 } }]);
            openModalWithFlows();

            click(buttonNamed('Edit Subgraph: Support shortcut'));
            expect(actionPicker().value).toBe('Subgraph');
            expect(flowPicker()!.value).toBe('Support');
            expect(saveButton().disabled).toBe(false);

            pickFlow('Billing');
            click(saveButton());

            expect(customRows()).toEqual([{ label: 'Subgraph: Billing', keys: 'Alt 1' }]);
            expect(nextPatch().body).toEqual({
                custom_shortcuts: { custom: [{ action: 'node.subgraph', keys: 'Alt+Digit1', params: { flowId: 12 } }] },
            });
        });

        it('names the flow of the Subgraph row that already has the recorded key, without firing it', () => {
            setUp();
            const subgraph = vi.fn();
            TestBed.inject(KeymapService).register('node.subgraph', subgraph);
            loadUser([{ action: 'node.subgraph', keys: 'Alt+Digit1', params: { flowId: 12 } }]);
            openModalWithFlows();

            startAdding();
            pickAction('Subgraph');
            pickFlow('Support');
            const recorded = record({ key: '1', code: 'Digit1', altKey: true });

            expect(subgraph).not.toHaveBeenCalled();
            expect(recorded.defaultPrevented).toBe(true);
            expect(feedback()).toBe('Already used by your Subgraph: Billing shortcut');
            expect(saveButton().disabled).toBe(true);
        });

        it('keeps a Subgraph row and its flow on reset to defaults, clearing only the node key it took', () => {
            setUp();
            loadUser([
                { action: 'node.subgraph', keys: 'Shift+KeyP', params: { flowId: 12 } },
                { action: 'node.subgraph', keys: 'Alt+Digit2', params: { flowId: 34 } },
            ]);
            openModalWithFlows();

            click(buttonNamed('Reset to defaults'));
            click(buttonNamed('Reset', document.querySelector('app-confirmation-dialog')!));

            expect(customRows()).toEqual([
                { label: 'Subgraph: Billing', keys: 'Not set' },
                { label: 'Subgraph: Support', keys: 'Alt 2' },
            ]);
            expect(nextPatch().body).toEqual({
                custom_shortcuts: {
                    custom: [
                        { action: 'node.subgraph', keys: null, params: { flowId: 12 } },
                        { action: 'node.subgraph', keys: 'Alt+Digit2', params: { flowId: 34 } },
                    ],
                },
            });
        });
    });

    describe('keyboard only', () => {
        const FLOWS: GetGraphLightRequest[] = [
            { id: 1, uuid: 'uuid-1', name: 'Onboarding', description: '' },
            { id: 12, uuid: 'uuid-12', name: 'Billing', description: '' },
        ];

        function openModalWithFlows(): void {
            fixture = TestBed.createComponent(ShortcutsModalComponent);
            fixture.componentRef.setInput('open', true);
            fixture.componentRef.setInput('pos', { top: 10, left: 10 });
            fixture.componentRef.setInput('flows', FLOWS);
            fixture.componentRef.setInput('currentFlowId', 1);
            closedCount = 0;
            fixture.componentInstance.closed.subscribe(() => (closedCount += 1));
            render();
        }

        function focused(): HTMLElement {
            return document.activeElement as HTMLElement;
        }

        function type(value: string): void {
            const input = focused() as HTMLInputElement;
            input.value = value;
            input.dispatchEvent(new Event('input'));
            render();
        }

        function enter(init: KeyboardEventInit = {}): KeyboardEvent {
            return press(focused(), { key: 'Enter', code: 'Enter', ...init });
        }

        function isRecording(): boolean {
            return text(keysBox()).includes('Press keys');
        }

        it('adds a node shortcut: type, Enter, keys record at once, Enter saves', () => {
            setUp();
            openModal();

            startAdding();
            type('Agent');
            enter();

            expect(focused()).toBe(keysBox());
            expect(isRecording()).toBe(true);

            press(keysBox(), { key: '1', code: 'Digit1', altKey: true });
            enter();

            expect(editor()).toBeNull();
            expect(customRows()).toEqual([{ label: 'Agent Node', keys: 'Alt 1' }]);
            expect(nextPatch().body).toEqual({
                custom_shortcuts: { custom: [{ action: 'node.agent', keys: 'Alt+Digit1' }] },
            });
        });

        it('adds a Subgraph shortcut through the Flow field', () => {
            setUp();
            openModalWithFlows();

            startAdding();
            type('Subg');
            enter();
            const flowField = focused() as HTMLInputElement;
            expect(flowField).not.toBe(actionPicker());
            expect(flowField.getAttribute('role')).toBe('combobox');

            type('Bill');
            enter();
            expect(isRecording()).toBe(true);
            press(keysBox(), { key: '1', code: 'Digit1', altKey: true });
            enter();

            expect(customRows()).toEqual([{ label: 'Subgraph: Billing', keys: 'Alt 1' }]);
            expect(nextPatch().body).toEqual({
                custom_shortcuts: { custom: [{ action: 'node.subgraph', keys: 'Alt+Digit1', params: { flowId: 12 } }] },
            });
        });

        it('edits only the key when Enter is pressed through the filled fields', () => {
            setUp();
            loadUser([{ action: 'node.subgraph', keys: 'Alt+Digit1', params: { flowId: 12 } }]);
            openModalWithFlows();

            click(buttonNamed('Edit Subgraph: Billing shortcut'));
            enter();
            expect((focused() as HTMLInputElement).value).toBe('Billing');
            enter();
            expect(isRecording()).toBe(true);
            press(keysBox(), { key: '2', code: 'Digit2', altKey: true });
            enter();

            expect(customRows()).toEqual([{ label: 'Subgraph: Billing', keys: 'Alt 2' }]);
            expect(nextPatch().body).toEqual({
                custom_shortcuts: { custom: [{ action: 'node.subgraph', keys: 'Alt+Digit2', params: { flowId: 12 } }] },
            });
        });

        it('selects the text of a search field when it gets focus', () => {
            setUp();
            loadUser([{ action: 'node.agent', keys: 'Alt+KeyB' }]);
            openModal();

            click(buttonNamed('Edit Agent Node shortcut'));

            expect(focused()).toBe(actionPicker());
            expect([actionPicker().selectionStart, actionPicker().selectionEnd]).toEqual([0, 'Agent Node'.length]);
        });

        function announcement(): string {
            return text(editor()!.querySelector('[aria-live="polite"]')!);
        }

        it('keeps recording on a second Enter before any key is pressed, and saves nothing', () => {
            setUp();
            openModal();

            startAdding();
            type('Agent');
            enter();
            enter();

            expect(editor()).not.toBeNull();
            expect(isRecording()).toBe(true);
            expect(announcement()).toBe('Press keys, or click Save to save without keys');
        });

        it('ignores a held Enter, before and after a key is recorded', () => {
            setUp();
            openModal();

            startAdding();
            type('Agent');
            enter();
            enter({ repeat: true });
            enter({ repeat: true });
            expect(isRecording()).toBe(true);

            press(keysBox(), { key: '1', code: 'Digit1', altKey: true });
            enter({ repeat: true });

            expect(editor()).not.toBeNull();
            expect(text(keysBox())).toContain('Alt+1');
        });

        it('does not start recording when the window gives focus back to the keys box', () => {
            setUp();
            openModal();

            startAdding();
            type('Agent');
            enter();
            press(keysBox(), { key: '1', code: 'Digit1', altKey: true });
            keysBox().blur();
            render();

            keysBox().focus();
            render();

            expect(isRecording()).toBe(false);
            expect(text(keysBox())).toContain('Alt+1');
        });

        it('starts recording when Tab brings focus to the keys box', () => {
            setUp();
            loadUser([{ action: 'node.agent', keys: 'Alt+KeyB' }]);
            openModal();

            click(buttonNamed('Edit Agent Node shortcut'));
            press(actionPicker(), { key: 'Tab', code: 'Tab' });
            keysBox().focus();
            render();

            expect(isRecording()).toBe(true);
        });

        it('does not save on Enter while the recorded key is refused', () => {
            setUp();
            openModal();

            startAdding();
            type('Agent');
            enter();
            press(keysBox(), { key: 's', code: 'KeyS', ctrlKey: true });
            enter();

            expect(editor()).not.toBeNull();
            expect(feedback()).toBe('Ctrl+S is reserved');
        });

        it.each([
            ['Ctrl+Enter', { ctrlKey: true }, 'Ctrl+Enter'],
            ['Shift+Enter, which is reserved', { shiftKey: true }, 'Shift+Enter'],
        ])('records %s as keys', (_case, modifiers, shown) => {
            setUp();
            openModal();

            startAdding();
            type('Agent');
            enter();
            enter(modifiers);

            expect(editor()).not.toBeNull();
            expect(isRecording()).toBe(false);
            expect(text(keysBox())).toContain(shown);
        });

        it('never fires the editor keymap while recording started by Enter', () => {
            setUp();
            const pythonNode = vi.fn();
            TestBed.inject(KeymapService).register('node.python', pythonNode);
            openModal();

            startAdding();
            type('Agent');
            enter();
            const recorded = press(keysBox(), { key: 'P', code: 'KeyP', shiftKey: true });

            expect(pythonNode).not.toHaveBeenCalled();
            expect(recorded.defaultPrevented).toBe(true);
            expect(text(keysBox())).toContain('Shift+P');
        });
    });
});
