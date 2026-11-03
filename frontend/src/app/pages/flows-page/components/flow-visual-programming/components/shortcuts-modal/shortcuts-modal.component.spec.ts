import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { NgZone } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { ActionCode, GetMeResponse, ResourceCode, ShortcutSettings } from '@shared/models';

import { GetGraphLightRequest } from '../../../../../../features/flows/models/graph.model';
import { ProfileService } from '../../../../../../services/auth/profile.service';
import { ConfigService } from '../../../../../../services/config';
import { ToastMessage, ToastService } from '../../../../../../services/notifications';
import { KeymapService, PLATFORM_IS_MAC } from '../../../../../../visual-programming/services/keymap.service';
import { grantPermissions } from '../../../../../../visual-programming/utils/testing/permissions.fixture';
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
    completed_tours: ['quick-start'],
    custom_shortcuts: { overrides: {}, custom: [] },
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

const BASE_SECTIONS = ['Editing', 'Navigating', 'Selection', 'Zoom', 'Flow actions', 'Nodes'];

const FLOW_ROWS_WINDOWS: readonly RenderedRow[] = [
    { label: 'Run', chords: [['Ctrl', 'Enter']] },
    { label: 'Stop session', chords: [['Ctrl', 'Shift', 'Enter']] },
    { label: 'Sessions', chords: [['Alt', 'S']] },
    { label: 'Open / close chat', chords: [['Alt', 'C']] },
    { label: 'Get cURL', chords: [['Alt', 'K']] },
    { label: 'Auto arrange', chords: [['Alt', 'L']] },
    { label: 'Add files', chords: [['Alt', 'U']] },
    { label: 'Export / Import menu', chords: [['Alt', 'X']] },
    { label: 'Extract to Subflow', chords: [['Alt', 'G']] },
    { label: 'Flow settings', chords: [['Alt', ',']] },
    { label: 'Domain', chords: [['Alt', 'M']] },
];

const FLOW_ROWS_MAC: readonly RenderedRow[] = [
    { label: 'Run', chords: [['⌘', '↩']] },
    { label: 'Stop session', chords: [['⌘', '⇧', '↩']] },
    { label: 'Sessions', chords: [['⌥', 'S']] },
    { label: 'Open / close chat', chords: [['⌥', 'C']] },
    { label: 'Get cURL', chords: [['⌥', 'K']] },
    { label: 'Auto arrange', chords: [['⌥', 'L']] },
    { label: 'Add files', chords: [['⌥', 'U']] },
    { label: 'Export / Import menu', chords: [['⌥', 'X']] },
    { label: 'Extract to Subflow', chords: [['⌥', 'G']] },
    { label: 'Flow settings', chords: [['⌥', ',']] },
    { label: 'Domain', chords: [['⌥', 'M']] },
];

/** Every permission a flow toolbar button checks, so every Flow actions row shows. */
const EVERY_FLOW_PERMISSION: Partial<Record<ResourceCode, ActionCode[]>> = {
    [ResourceCode.Flows]: [ActionCode.Read, ActionCode.Update, ActionCode.Use, ActionCode.Export],
    [ResourceCode.Files]: [ActionCode.Read],
};

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
    static observing = new Map<Element, ResizeObserverStub>();

    constructor(private readonly callback: ResizeObserverCallback) {}

    static resize(target: Element): void {
        const observer = ResizeObserverStub.observing.get(target);
        observer?.callback([], observer as unknown as ResizeObserver);
    }

    observe(target: Element): void {
        ResizeObserverStub.observing.set(target, this);
    }
    unobserve(target: Element): void {
        ResizeObserverStub.observing.delete(target);
    }
    disconnect(): void {
        ResizeObserverStub.observing.forEach((observer, target) => {
            if (observer === this) ResizeObserverStub.observing.delete(target);
        });
    }
}

describe('ShortcutsModalComponent', () => {
    let fixture: ComponentFixture<ShortcutsModalComponent>;
    let httpMock: HttpTestingController;
    let toasts: ToastMessage[];
    let closedCount: number;

    let frames = new Map<number, FrameRequestCallback>();
    let lastFrameId = 0;

    function setUp(isMac = false): void {
        vi.stubGlobal('ResizeObserver', ResizeObserverStub);
        frames = new Map();
        vi.stubGlobal('requestAnimationFrame', (callback: FrameRequestCallback) => {
            lastFrameId += 1;
            frames.set(lastFrameId, callback);
            return lastFrameId;
        });
        vi.stubGlobal('cancelAnimationFrame', (id: number) => frames.delete(id));
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
        grantPermissions(EVERY_FLOW_PERMISSION);
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
        for (let round = 0; round < 5 && frames.size > 0; round++) {
            const due = [...frames.values()];
            frames.clear();
            TestBed.inject(NgZone).run(() => due.forEach((callback) => callback(0)));
            fixture.detectChanges();
            TestBed.tick();
        }
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
            } else if (node.classList.contains('shortcuts__arrow-keys')) {
                if (chords.length === 0) chords.push([]);
                chords[chords.length - 1].push(node.getAttribute('aria-label') ?? '');
            }
        });
        return { label: text(row.querySelector('.shortcuts__label')!), chords };
    }

    function nodeRow(label: string): string {
        const row = rowElementsOf('Nodes').find((candidate) => readRow(candidate).label === label)!;
        return text(row.querySelector('.shortcuts__keys')!);
    }

    function customRows(): RenderedCustomRow[] {
        return rowElementsOf('Additional').map((row) => ({
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
            vi.restoreAllMocks();
            vi.useRealTimers();
        }
    });

    it('shows the heading it is given', () => {
        setUp();
        openModal();
        fixture.componentRef.setInput('heading', 'Command & Shortcuts');
        render();

        expect(text(root().querySelector('.shortcuts__header-title')!)).toBe('Command & Shortcuts');
    });

    it('shows the sections in order, Flow actions just before Nodes', () => {
        setUp();
        openModal();

        expect(sectionTitles()).toEqual(BASE_SECTIONS);
    });

    // The columns can only keep a heading with its rows when both sit in one unbreakable box; the rest of
    // the rows stay outside it so a long section can still continue in the next column.
    // This covers the markup only: jsdom has no column layout. The column break itself was checked in the browser.
    it('keeps every section heading in one box with its first row only', () => {
        setUp();
        loadUser([
            { action: 'node.agent', keys: 'Alt+KeyB' },
            { action: 'editing.save', keys: null },
        ]);
        openModal();

        const headingBoxes = [...BASE_SECTIONS, 'Additional'].map((title) => {
            const [firstRow, secondRow] = rowElementsOf(title);
            const box = cardOf(title).querySelector('.shortcuts__card-title')!.parentElement!;
            return { title, holdsFirstRow: box.contains(firstRow), holdsSecondRow: box.contains(secondRow) };
        });

        expect(headingBoxes).toEqual(
            [...BASE_SECTIONS, 'Additional'].map((title) => ({ title, holdsFirstRow: true, holdsSecondRow: false }))
        );
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
            { label: 'Move canvas', chords: [['Arrow keys']] },
            { label: 'Move canvas faster', chords: [['Ctrl', 'Arrow keys']] },
            { label: 'Previous / next page', chords: [['Alt', 'Up or Down arrow']] },
            { label: 'Open node create menu', chords: [['Right click']] },
        ]);
    });

    it('draws one-character keys as square keycaps and keeps word keys wide', () => {
        setUp(true);
        openModal();

        const searchRow = rowElementsOf('Navigating').find((row) => readRow(row).label === 'Node search')!;
        const squareKeys = Array.from(searchRow.querySelectorAll('.shortcuts__key'), (key) =>
            key.classList.contains('shortcuts__key--square')
        );
        expect(squareKeys).toEqual([true, true]); // ⌘ and F

        const deleteRow = rowElementsOf('Editing').find((row) => readRow(row).label === 'Delete')!;
        expect(deleteRow.querySelector('.shortcuts__key--square')).toBeNull();
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
            { label: 'Move selected nodes', chords: [['Arrow keys']] },
            { label: 'Move selected nodes faster', chords: [[zoneChords[0][0], 'Arrow keys']] },
        ]);
    });

    it('shows the zoom keys and gestures', () => {
        setUp();
        openModal();

        expect(rowsOf('Zoom')).toEqual([
            { label: 'Zoom in', chords: [['Ctrl', '+'], ['Mouse wheel up']] },
            { label: 'Zoom out', chords: [['Ctrl', '-'], ['Mouse wheel down']] },
        ]);
    });

    it.each([
        ['Windows/Linux', false, FLOW_ROWS_WINDOWS],
        ['macOS', true, FLOW_ROWS_MAC],
    ])('lists every flow toolbar action with its key on %s', (_platform, isMac, expected) => {
        setUp(isMac);
        openModal();

        expect(rowsOf('Flow actions')).toEqual(expected);
    });

    describe('flow actions the user may not use', () => {
        const FLOW_LABELS = FLOW_ROWS_WINDOWS.map((row) => row.label);

        function flowRowLabels(): string[] {
            return rowsOf('Flow actions').map((row) => row.label);
        }

        function pickableFlowActions(): string[] {
            startAdding();
            const input = actionPicker();
            input.value = '';
            input.dispatchEvent(new Event('input'));
            render();
            const options = Array.from(editor()!.querySelectorAll('[role="option"]'), text);
            click(buttonNamed('Cancel', editor()!));
            return options.filter((label) => FLOW_LABELS.includes(label));
        }

        function without(...hidden: string[]): string[] {
            return FLOW_LABELS.filter((label) => !hidden.includes(label));
        }

        it.each([
            [
                'no access to files',
                { [ResourceCode.Flows]: [ActionCode.Read, ActionCode.Update, ActionCode.Use, ActionCode.Export] },
                ['Add files'],
            ],
            [
                'no Use on flows',
                {
                    [ResourceCode.Flows]: [ActionCode.Read, ActionCode.Update, ActionCode.Export],
                    [ResourceCode.Files]: [ActionCode.Read],
                },
                ['Run', 'Stop session', 'Get cURL'],
            ],
            [
                'neither Export nor Update on flows',
                { [ResourceCode.Flows]: [ActionCode.Read, ActionCode.Use], [ResourceCode.Files]: [ActionCode.Read] },
                ['Export / Import menu'],
            ],
            [
                'Export without Update on flows',
                {
                    [ResourceCode.Flows]: [ActionCode.Read, ActionCode.Use, ActionCode.Export],
                    [ResourceCode.Files]: [ActionCode.Read],
                },
                [],
            ],
            [
                'Update without Export on flows',
                {
                    [ResourceCode.Flows]: [ActionCode.Read, ActionCode.Update, ActionCode.Use],
                    [ResourceCode.Files]: [ActionCode.Read],
                },
                [],
            ],
        ])(
            'with %s, leaves the actions whose buttons are hidden out of the list and the picker',
            (_user, permissions, hidden) => {
                setUp();
                grantPermissions(permissions);
                openModal();

                expect(flowRowLabels()).toEqual(without(...hidden));
                expect(pickableFlowActions()).toEqual(without(...hidden));
            }
        );

        it('shows the rows once the permission arrives while the list is open', () => {
            setUp();
            loadUser([{ action: 'flow.add-files', keys: 'Alt+KeyJ' }]);
            grantPermissions({ [ResourceCode.Flows]: [ActionCode.Read, ActionCode.Update, ActionCode.Export] });
            openModal();
            expect(flowRowLabels()).toEqual(without('Run', 'Stop session', 'Get cURL', 'Add files'));
            expect(sectionTitles()).toEqual(BASE_SECTIONS);

            grantPermissions(EVERY_FLOW_PERMISSION);
            render();

            expect(flowRowLabels()).toEqual(FLOW_LABELS);
            expect(customRows()).toEqual([{ label: 'Add files', keys: 'Alt J' }]);
        });

        it('hides a saved Additional row for such an action but keeps it in what is saved', () => {
            setUp();
            loadUser([
                { action: 'flow.run', keys: 'Alt+KeyJ' },
                { action: 'node.task', keys: 'Alt+KeyB' },
            ]);
            grantPermissions({ [ResourceCode.Flows]: [ActionCode.Read, ActionCode.Update] });
            openModal();
            expect(customRows()).toEqual([{ label: 'Task Node', keys: 'Alt B' }]);

            click(buttonNamed('Delete Task Node shortcut'));

            expect(sectionTitles()).toEqual(BASE_SECTIONS);
            expect(nextPatch().body).toEqual({
                custom_shortcuts: { overrides: {}, custom: [{ action: 'flow.run', keys: 'Alt+KeyJ' }] },
            });
        });

        it('treats the key of an action the user cannot see as free, and saving takes it from that action', () => {
            setUp();
            loadUser([]);
            grantPermissions({ [ResourceCode.Flows]: [ActionCode.Read, ActionCode.Update] });
            openModal();

            startAdding();
            pickAction('Save');
            record({ key: 'u', code: 'KeyU', altKey: true });

            expect(feedback()).toBe('');
            click(saveButton());
            expect(customRows()).toEqual([{ label: 'Save', keys: 'Alt U' }]);
            const patch = nextPatch();
            expect(patch.body).toEqual({
                custom_shortcuts: { overrides: {}, custom: [{ action: 'editing.save', keys: 'Alt+KeyU' }] },
            });
            patch.succeed();

            grantPermissions(EVERY_FLOW_PERMISSION);
            render();
            const addFiles = rowElementsOf('Flow actions').find((row) => readRow(row).label === 'Add files')!;
            expect(text(addFiles.querySelector('.shortcuts__keys')!)).toBe('Not set');
        });

        it('refuses a key a hidden Additional row holds without naming that row', () => {
            setUp();
            loadUser([{ action: 'flow.add-files', keys: 'Alt+KeyJ' }]);
            grantPermissions({ [ResourceCode.Flows]: [ActionCode.Read, ActionCode.Update] });
            openModal();

            startAdding();
            pickAction('Save');
            record({ key: 'j', code: 'KeyJ', altKey: true });

            expect(feedback()).toBe('Alt+J is already in use');
            expect(saveButton().disabled).toBe(true);
        });

        it('counts a hidden Additional row among the keys Reset to defaults clears, as it changes what is saved', () => {
            setUp();
            loadUser([{ action: 'flow.add-files', keys: 'Shift+KeyP' }]);
            grantPermissions({ [ResourceCode.Flows]: [ActionCode.Read, ActionCode.Update] });
            openModal();

            click(buttonNamed('Reset to defaults'));
            const dialog = document.querySelector('app-confirmation-dialog')!;

            expect(text(dialog.querySelector('.dialog-message')!)).toBe(
                '1 additional shortcut will lose its key. Every node and flow action gets its own key back.'
            );
            click(buttonNamed('Cancel', dialog));
        });
    });

    describe('base rows', () => {
        it('show only the built-in key; the extra key is listed under Additional', () => {
            setUp();
            loadUser([{ action: 'node.python', keys: 'Shift+KeyB' }]);
            openModal();

            expect(rowsOf('Nodes')[0]).toEqual({ label: 'Python Code Node', chords: [['Shift', 'P']] });
            expect(customRows()).toEqual([{ label: 'Python Code Node', keys: 'Shift B' }]);
        });

        it('say Not set for a node whose key an additional shortcut took', () => {
            setUp();
            loadUser([{ action: 'node.agent', keys: 'Shift+KeyP' }]);
            openModal();

            expect(nodeRow('Python Code Node')).toBe('Not set');
            expect(nodeRow('Agent Node')).toBe('Shift A');
        });

        it('have no controls outside Flow actions and Nodes', () => {
            setUp();
            loadUser([{ action: 'node.agent', keys: 'Shift+KeyP' }]);
            openModal();

            for (const title of BASE_SECTIONS.filter((section) => section !== 'Flow actions' && section !== 'Nodes')) {
                expect(cardOf(title).querySelectorAll('button')).toHaveLength(0);
            }
        });
    });

    describe('additional section', () => {
        it('is hidden while the user has no additional shortcuts', () => {
            setUp();
            openModal();

            expect(sectionTitles()).toEqual(BASE_SECTIONS);
            expect(hasButton('Add shortcut')).toBe(true);
        });

        it('lists each additional shortcut with its keys, or Not set, after Nodes', () => {
            setUp();
            loadUser([
                { action: 'node.agent', keys: 'Alt+KeyB' },
                { action: 'editing.save', keys: null },
            ]);
            openModal();

            expect(sectionTitles()).toEqual([...BASE_SECTIONS, 'Additional']);
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
            expect(patch.body).toEqual({
                custom_shortcuts: { overrides: {}, custom: [{ action: 'node.task', keys: 'Alt+KeyK' }] },
            });
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
                custom_shortcuts: { overrides: {}, custom: [{ action: 'node.agent', keys: 'Shift+KeyP' }] },
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
                'a key another additional shortcut has',
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

            expect(actionPicker().value).toBe('Stop session');
            expect(editor()!.querySelector('[role="listbox"]')).toBeNull();
            expect(document.activeElement).toBe(keysBox());
        });

        it.each([
            [99, ''],
            [100, 'You can have up to 100 additional shortcuts'],
        ])('with %i additional shortcuts saved, says "%s" about one more', (count, message) => {
            setUp();
            loadUser(Array.from({ length: count }, () => ({ action: 'node.agent', keys: null })));
            openModal();

            startAdding();
            pickAction('Task Node');
            record({ key: 'y', code: 'KeyY', altKey: true });

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
                    overrides: {},
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
            expect(patch.body).toEqual({
                custom_shortcuts: { overrides: {}, custom: [{ action: 'node.agent', keys: null }] },
            });
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
        it('is hidden while no additional shortcut holds a node key', () => {
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
                { action: 'editing.save', keys: 'Alt+KeyO' },
            ]);
            openModal();

            click(buttonNamed('Reset to defaults'));
            const dialog = document.querySelector('app-confirmation-dialog')!;
            expect(text(dialog.querySelector('.dialog-message')!)).toBe(
                '2 additional shortcuts will lose their keys. Every node and flow action gets its own key back.'
            );

            click(buttonNamed('Reset', dialog));

            expect(nodeRow('Python Code Node')).toBe('Shift P');
            expect(nodeRow('Agent Node')).toBe('Shift A');
            expect(customRows()).toEqual([
                { label: 'Agent Node', keys: 'Not set' },
                { label: 'Task Node', keys: 'Not set' },
                { label: 'Save', keys: 'Alt O' },
            ]);
            expect(hasButton('Reset to defaults')).toBe(false);
            const patch = nextPatch();
            expect(patch.body).toEqual({
                custom_shortcuts: {
                    overrides: {},
                    custom: [
                        { action: 'node.agent', keys: null },
                        { action: 'node.task', keys: null },
                        { action: 'editing.save', keys: 'Alt+KeyO' },
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
                '1 additional shortcut will lose its key. Every node and flow action gets its own key back.'
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
            return rowElementsOf('Additional')[index].querySelector('.shortcuts__label')!;
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
                custom_shortcuts: {
                    overrides: {},
                    custom: [{ action: 'node.subgraph', keys: 'Alt+Digit1', params: { flowId: 34 } }],
                },
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
                custom_shortcuts: {
                    overrides: {},
                    custom: [{ action: 'node.subgraph', keys: 'Alt+Digit1', params: { flowId: 12 } }],
                },
            });
        });

        it('does not offer Subgraph when no other flow can be picked, but keeps and edits an existing row', () => {
            setUp();
            loadUser([{ action: 'node.subgraph', keys: 'Alt+Digit1', params: { flowId: 99 } }]);
            openModalWithFlows([THIS_FLOW]);

            startAdding();
            expect(actionOptions('Subg')).toEqual([]);
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
                custom_shortcuts: {
                    overrides: {},
                    custom: [{ action: 'node.subgraph', keys: 'Alt+Digit1', params: { flowId: 34 } }],
                },
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
                custom_shortcuts: {
                    overrides: {},
                    custom: [{ action: 'node.subgraph', keys: 'Alt+Digit1', params: { flowId: 12 } }],
                },
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
                    overrides: {},
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
                custom_shortcuts: { overrides: {}, custom: [{ action: 'node.agent', keys: 'Alt+Digit1' }] },
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
                custom_shortcuts: {
                    overrides: {},
                    custom: [{ action: 'node.subgraph', keys: 'Alt+Digit1', params: { flowId: 12 } }],
                },
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
                custom_shortcuts: {
                    overrides: {},
                    custom: [{ action: 'node.subgraph', keys: 'Alt+Digit2', params: { flowId: 12 } }],
                },
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

    describe('room for the editor', () => {
        function listbox(): HTMLElement {
            return editor()!.querySelector('[role="listbox"]')!;
        }

        it('opens the action list as a dropdown over the editor, not in its flow', () => {
            setUp();
            openModal();

            startAdding();

            expect(listbox().parentElement!.classList).toContain('shortcut-picker__anchor');
            expect(listbox().parentElement!.querySelector('input[role="combobox"]')).toBe(actionPicker());
            expect(getComputedStyle(listbox()).position).toBe('absolute');
        });

        it('opens the list upward when there is no room below it in the column', () => {
            setUp();
            openModal();
            const content = root().querySelector<HTMLElement>('.shortcuts__content')!;
            vi.spyOn(Element.prototype, 'getBoundingClientRect').mockImplementation(function (this: Element) {
                const isInput = this instanceof HTMLInputElement;
                return DOMRect.fromRect(
                    isInput ? { x: 0, y: 500, width: 200, height: 32 } : { x: 0, y: 0, width: 900, height: 560 }
                );
            });
            content.style.overflowY = 'auto';

            startAdding();

            expect(listbox().classList).toContain('shortcut-picker__list--up');
            expect(listbox().style.maxHeight).toBe('200px');
        });

        const FLOW_WIDTH_PX = 980;
        const COLUMN_GAP_PX = 40;

        function columnPitch(): number {
            const isFourColumns = root().querySelector('.shortcuts__modal--four-columns') !== null;
            return (FLOW_WIDTH_PX + COLUMN_GAP_PX) / (isFourColumns ? 4 : 3);
        }

        function layOut(
            lastItemColumn: () => number,
            flowScrollHeight = 400,
            lastItemTop: () => number = () => 0
        ): HTMLElement {
            const content = root().querySelector<HTMLElement>('.shortcuts__content')!;
            const flow = root().querySelector<HTMLElement>('.shortcuts__flow')!;
            Object.defineProperty(content, 'clientHeight', { configurable: true, value: 560 });
            Object.defineProperty(flow, 'clientWidth', { configurable: true, value: FLOW_WIDTH_PX });
            Object.defineProperty(flow, 'scrollHeight', { configurable: true, value: flowScrollHeight });
            const realRect = Element.prototype.getBoundingClientRect;
            vi.spyOn(Element.prototype, 'getBoundingClientRect').mockImplementation(function (this: Element) {
                if (this === flow.lastElementChild) {
                    return DOMRect.fromRect({
                        x: lastItemColumn() * columnPitch(),
                        y: lastItemTop(),
                        width: 300,
                        height: 40,
                    });
                }
                return this === flow ? DOMRect.fromRect({ x: 0, y: 0, width: 980, height: 560 }) : realRect.call(this);
            });
            return content;
        }

        function columnLayout(): string {
            const modal = root().querySelector('.shortcuts__modal')!;
            const content = root().querySelector('.shortcuts__content')!;
            if (content.classList.contains('shortcuts__content--scrolling')) return 'vertical scroll';
            return modal.classList.contains('shortcuts__modal--four-columns') ? '4 columns' : '3 columns';
        }

        function refit(): void {
            ResizeObserverStub.resize(root().querySelector('.shortcuts__content')!);
            render();
        }

        function pass(milliseconds: number): void {
            TestBed.inject(NgZone).run(() => vi.advanceTimersByTime(milliseconds));
            render();
        }

        function preferReducedMotion(): void {
            vi.stubGlobal('matchMedia', (query: string) => ({
                matches: query === '(prefers-reduced-motion: reduce)',
                media: query,
                addListener: () => undefined,
                removeListener: () => undefined,
                addEventListener: () => undefined,
                removeEventListener: () => undefined,
            }));
        }

        function isFading(): boolean {
            return root().querySelector('.shortcuts__flow')!.classList.contains('shortcuts__flow--reflowing');
        }

        it('opens with the rows hidden and shows them only once the final layout is chosen', () => {
            setUp();
            fixture = TestBed.createComponent(ShortcutsModalComponent);
            fixture.componentRef.setInput('open', true);
            fixture.componentRef.setInput('pos', { top: 10, left: 10 });
            fixture.detectChanges();
            TestBed.tick();
            layOut(() => (columnLayout() === '3 columns' ? 5 : 2), 900);

            expect(isFading()).toBe(true);

            render();

            expect([isFading(), columnLayout()]).toEqual([false, 'vertical scroll']);
        });

        it('fades the rows out, changes the columns while they are hidden, and fades them back in after the resize', () => {
            setUp();
            openModal();
            layOut(() => 3);
            vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] });

            ResizeObserverStub.resize(root().querySelector('.shortcuts__content')!);
            render();
            expect([isFading(), columnLayout()]).toEqual([true, '3 columns']);

            pass(120);
            expect([isFading(), columnLayout()]).toEqual([true, '4 columns']);

            pass(200);
            expect([isFading(), columnLayout()]).toEqual([false, '4 columns']);
        });

        it('does not change the columns while the panel is still widening after Expand', () => {
            setUp();
            openModal();
            let lastColumn = 2;
            layOut(() => lastColumn);
            vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] });
            click(root().querySelector('.shortcuts__size-btn')!);
            render();

            click(root().querySelector('.shortcuts__size-btn')!);
            render();
            lastColumn = 3;
            ResizeObserverStub.resize(root().querySelector('.shortcuts__content')!);
            render();
            expect([isFading(), columnLayout()]).toEqual([false, '3 columns']);

            lastColumn = 2;
            pass(200);
            expect([isFading(), columnLayout()]).toEqual([false, '3 columns']);
        });

        it('shows the rows again when Expand cuts a column change short', () => {
            setUp();
            openModal();
            layOut(() => 3);
            vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] });
            ResizeObserverStub.resize(root().querySelector('.shortcuts__content')!);
            render();
            click(root().querySelector('.shortcuts__size-btn')!);
            render();
            pass(120);

            click(root().querySelector('.shortcuts__size-btn')!);
            render();
            pass(200);

            expect([isFading(), columnLayout()]).toEqual([false, '4 columns']);
        });

        it('drops a column change that was still fading when the list closed', () => {
            setUp();
            openModal();
            layOut(() => 3);
            vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] });
            ResizeObserverStub.resize(root().querySelector('.shortcuts__content')!);
            render();
            expect(isFading()).toBe(true);

            fixture.componentRef.setInput('open', false);
            render();
            fixture.componentRef.setInput('open', true);
            render();
            pass(400);

            expect([isFading(), columnLayout()]).toEqual([false, '3 columns']);
        });

        it('changes the columns at once when the user prefers reduced motion', () => {
            preferReducedMotion();
            setUp();
            openModal();
            layOut(() => 3);

            ResizeObserverStub.resize(root().querySelector('.shortcuts__content')!);
            render();

            expect([isFading(), columnLayout()]).toEqual([false, '4 columns']);
        });

        it('goes back to three columns when the rows end in the third column, even with no room to spare', () => {
            preferReducedMotion();
            setUp();
            openModal();
            let lastColumn = 3;
            layOut(
                () => lastColumn,
                400,
                () => 500
            );
            refit();

            lastColumn = 2;
            refit();

            expect(columnLayout()).toBe('3 columns');
        });

        it.each([
            ['few rows', 0, '3 columns'],
            ['rows that end in the third column', 2, '3 columns'],
            ['rows that overflow three columns', 3, '4 columns'],
            ['rows that overflow four columns', 4, 'vertical scroll'],
        ])('shows %s (last item in column %i) as %s', (_case, lastColumn, layout) => {
            preferReducedMotion();
            setUp();
            openModal();
            layOut(() => lastColumn);

            refit();

            expect(columnLayout()).toBe(layout);
        });

        it('goes back to three columns once the rows fit again', () => {
            preferReducedMotion();
            setUp();
            openModal();
            let lastColumn = 3;
            layOut(() => lastColumn);
            refit();
            expect(columnLayout()).toBe('4 columns');

            lastColumn = 1;
            refit();

            expect(columnLayout()).toBe('3 columns');
        });

        it('switches to vertical scrolling instead of a sideways column when the open editor does not fit', () => {
            preferReducedMotion();
            setUp();
            openModal();
            const content = layOut(() => (editor() === null ? 2 : 5));
            content.scrollLeft = 300;

            startAdding();
            ResizeObserverStub.resize(editor()!);
            render();

            expect(columnLayout()).toBe('vertical scroll');
            expect(content.scrollLeft).toBe(0);

            press(actionPicker(), { key: 'Escape', code: 'Escape' });
            press(actionPicker(), { key: 'Escape', code: 'Escape' });
            refit();

            expect(editor()).toBeNull();
            expect(columnLayout()).not.toBe('vertical scroll');
        });

        it('keeps scrolling vertically while the rows still do not fit four columns', () => {
            preferReducedMotion();
            setUp();
            openModal();
            layOut(() => 5, 900);
            refit();

            refit();

            expect(columnLayout()).toBe('vertical scroll');
        });

        it('keeps the Add shortcut label when the button is clipped for a moment', () => {
            setUp();
            vi.spyOn(Element.prototype, 'getBoundingClientRect').mockReturnValue(
                DOMRect.fromRect({ x: 5000, y: 0, width: 120, height: 28 })
            );

            openModal();
            render();

            const addButton = buttonNamed('Add shortcut');
            expect(addButton.classList).not.toContain('btn--only-icon');
            expect(text(addButton)).toBe('Add shortcut');
        });
    });

    describe('node keys', () => {
        function loadSettings(settings: unknown): void {
            TestBed.inject(ProfileService).getCurrentUser().subscribe();
            httpMock.expectOne({ method: 'GET', url: PROFILE_URL }).flush({ ...BASE_USER, custom_shortcuts: settings });
        }

        function rowMessage(): string {
            const message = cardOf('Nodes').querySelector('.shortcuts__row-feedback');
            return message ? text(message) : '';
        }

        it('edits only the key of a node row and keeps its reset next to it', () => {
            setUp();
            openModal();

            click(buttonNamed('Edit Python Code Node key'));

            expect(editor()!.querySelector('input[role="combobox"]')).toBeNull();
            expect(document.activeElement).toBe(keysBox());
            expect(text(keysBox())).toContain('Press keys');
            expect(hasButton('Reset Python Code Node key')).toBe(false);

            press(keysBox(), { key: 'q', code: 'KeyQ', altKey: true });
            press(keysBox(), { key: 'Enter', code: 'Enter' });

            expect(editor()).toBeNull();
            expect(nodeRow('Python Code Node')).toBe('Alt Q');
            expect(hasButton('Reset Python Code Node key')).toBe(true);
            expect(document.activeElement).toBe(buttonNamed('Edit Python Code Node key'));
            expect(nextPatch().body).toEqual({
                custom_shortcuts: { custom: [], overrides: { 'node.python': 'Alt+KeyQ' } },
            });
        });

        it("warns before taking another node's key and leaves that node Not set", () => {
            setUp();
            openModal();

            click(buttonNamed('Edit Python Code Node key'));
            press(keysBox(), { key: 'T', code: 'KeyT', shiftKey: true });

            expect(feedback()).toBe("Shift+T is Task Node's key — saving moves it here; Task Node will have no key");
            click(saveButton());

            expect(nodeRow('Python Code Node')).toBe('Shift T');
            expect(nodeRow('Task Node')).toBe('Not set');
            nextPatch().succeed();
        });

        it('refuses an Additional key for a node row', () => {
            setUp();
            loadUser([{ action: 'node.agent', keys: 'Alt+KeyB' }]);
            openModal();

            click(buttonNamed('Edit Python Code Node key'));
            press(keysBox(), { key: 'b', code: 'KeyB', altKey: true });

            expect(feedback()).toBe('Already used by your Agent Node shortcut');
            expect(saveButton().disabled).toBe(true);
        });

        it('can clear a node key, which then shows Not set with a reset', () => {
            setUp();
            openModal();

            click(buttonNamed('Edit Python Code Node key'));
            press(keysBox(), { key: 'Escape', code: 'Escape' });
            click(buttonNamed('Clear keys', editor()!));
            keysBox().blur();
            render();
            click(saveButton());

            expect(nodeRow('Python Code Node')).toBe('Not set');
            expect(hasButton('Reset Python Code Node key')).toBe(true);
            expect(nextPatch().body).toEqual({ custom_shortcuts: { custom: [], overrides: { 'node.python': null } } });
        });

        it('gives a node whose key an Additional row took a new key', () => {
            setUp();
            loadUser([{ action: 'node.agent', keys: 'Shift+KeyP' }]);
            openModal();
            expect(nodeRow('Python Code Node')).toBe('Not set');

            click(buttonNamed('Edit Python Code Node key'));
            press(keysBox(), { key: 'q', code: 'KeyQ', altKey: true });
            click(saveButton());

            expect(nodeRow('Python Code Node')).toBe('Alt Q');
            nextPatch().succeed();
        });

        it('shows reset only on changed node rows and gives the node its own key back', () => {
            setUp();
            loadSettings({ custom: [], overrides: { 'node.python': 'Alt+KeyQ' } });
            openModal();

            expect(hasButton('Reset Python Code Node key')).toBe(true);
            expect(hasButton('Reset Task Node key')).toBe(false);

            click(buttonNamed('Reset Python Code Node key'));

            expect(nodeRow('Python Code Node')).toBe('Shift P');
            expect(hasButton('Reset Python Code Node key')).toBe(false);
            expect(nextPatch().body).toEqual({ custom_shortcuts: { custom: [], overrides: {} } });
        });

        it('says who holds the default when a node key cannot be reset', () => {
            setUp();
            loadSettings({
                custom: [{ action: 'node.agent', keys: 'Shift+KeyP' }],
                overrides: { 'node.python': 'Alt+KeyQ' },
            });
            openModal();

            click(buttonNamed('Reset Python Code Node key'));

            expect(rowMessage()).toBe('Already used by your Agent Node shortcut');
            expect(nodeRow('Python Code Node')).toBe('Alt Q');
        });

        it('offers Reset to defaults for changed node keys alone and clears them', () => {
            setUp();
            loadSettings({ custom: [], overrides: { 'node.python': 'Alt+KeyQ' } });
            openModal();

            click(buttonNamed('Reset to defaults'));
            const dialog = document.querySelector('app-confirmation-dialog')!;
            expect(text(dialog.querySelector('.dialog-message')!)).toBe(
                'Every node and flow action gets its own key back.'
            );
            click(buttonNamed('Reset', dialog));

            expect(nodeRow('Python Code Node')).toBe('Shift P');
            expect(nextPatch().body).toEqual({ custom_shortcuts: { custom: [], overrides: {} } });
        });

        it('closes the node key editor on Esc and returns focus to its edit button', () => {
            setUp();
            openModal();

            click(buttonNamed('Edit Python Code Node key'));
            press(keysBox(), { key: 'Escape', code: 'Escape' });
            press(keysBox(), { key: 'Escape', code: 'Escape' });

            expect(editor()).toBeNull();
            expect(document.activeElement).toBe(buttonNamed('Edit Python Code Node key'));
            expect(closedCount).toBe(0);
        });
    });

    describe('flow keys', () => {
        function loadSettings(settings: unknown): void {
            TestBed.inject(ProfileService).getCurrentUser().subscribe();
            httpMock.expectOne({ method: 'GET', url: PROFILE_URL }).flush({ ...BASE_USER, custom_shortcuts: settings });
        }

        function flowRow(label: string): string {
            const row = rowElementsOf('Flow actions').find((candidate) => readRow(candidate).label === label)!;
            return text(row.querySelector('.shortcuts__keys')!);
        }

        it('offers an edit button on every flow row', () => {
            setUp();
            openModal();

            for (const { label } of FLOW_ROWS_WINDOWS) {
                expect(hasButton(`Edit ${label} key`, cardOf('Flow actions'))).toBe(true);
            }
        });

        it('edits only the key of a flow row, saves the override and returns focus to its edit button', () => {
            setUp();
            openModal();

            click(buttonNamed('Edit Open / close chat key'));

            expect(editor()!.querySelector('input[role="combobox"]')).toBeNull();
            press(keysBox(), { key: 'j', code: 'KeyJ', altKey: true });
            press(keysBox(), { key: 'Enter', code: 'Enter' });

            expect(editor()).toBeNull();
            expect(flowRow('Open / close chat')).toBe('Alt J');
            expect(hasButton('Reset Open / close chat key')).toBe(true);
            expect(document.activeElement).toBe(buttonNamed('Edit Open / close chat key'));
            expect(nextPatch().body).toEqual({
                custom_shortcuts: { custom: [], overrides: { 'flow.chat': 'Alt+KeyJ' } },
            });
        });

        it('says Not set on the chat row when an Additional shortcut already uses Alt+C', () => {
            setUp();
            loadUser([{ action: 'editing.save', keys: 'Alt+KeyC' }]);
            openModal();

            expect(flowRow('Open / close chat')).toBe('Not set');
            expect(customRows()).toEqual([{ label: 'Save', keys: 'Alt C' }]);
        });

        it('gives a flow action its own key back with its reset button', () => {
            setUp();
            loadSettings({ custom: [], overrides: { 'flow.chat': 'Alt+KeyJ' } });
            openModal();

            expect(hasButton('Reset Run key')).toBe(false);
            click(buttonNamed('Reset Open / close chat key'));

            expect(flowRow('Open / close chat')).toBe('Alt C');
            expect(hasButton('Reset Open / close chat key')).toBe(false);
            expect(nextPatch().body).toEqual({ custom_shortcuts: { custom: [], overrides: {} } });
        });

        it('edits the Stop session key and saves the override', () => {
            setUp();
            openModal();

            click(buttonNamed('Edit Stop session key'));
            press(keysBox(), { key: 'j', code: 'KeyJ', altKey: true });
            press(keysBox(), { key: 'Enter', code: 'Enter' });

            expect(flowRow('Stop session')).toBe('Alt J');
            expect(hasButton('Reset Stop session key')).toBe(true);
            expect(nextPatch().body).toEqual({
                custom_shortcuts: { custom: [], overrides: { 'flow.stop-session': 'Alt+KeyJ' } },
            });
        });

        it('gives Stop session Ctrl+Shift+Enter back with its reset button', () => {
            setUp();
            loadSettings({ custom: [], overrides: { 'flow.stop-session': 'Alt+KeyJ' } });
            openModal();

            click(buttonNamed('Reset Stop session key'));

            expect(flowRow('Stop session')).toBe('Ctrl Shift Enter');
            expect(hasButton('Reset Stop session key')).toBe(false);
            expect(nextPatch().body).toEqual({ custom_shortcuts: { custom: [], overrides: {} } });
        });

        it('gives changed flow keys back on Reset to defaults and clears the Additional key on one of them', () => {
            setUp();
            loadSettings({
                custom: [{ action: 'editing.save', keys: 'Alt+KeyC' }],
                overrides: { 'flow.run': 'Alt+KeyR' },
            });
            openModal();

            click(buttonNamed('Reset to defaults'));
            const dialog = document.querySelector('app-confirmation-dialog')!;
            expect(text(dialog.querySelector('.dialog-message')!)).toBe(
                '1 additional shortcut will lose its key. Every node and flow action gets its own key back.'
            );
            click(buttonNamed('Reset', dialog));

            expect(flowRow('Run')).toBe('Ctrl Enter');
            expect(flowRow('Open / close chat')).toBe('Alt C');
            expect(nextPatch().body).toEqual({
                custom_shortcuts: { custom: [{ action: 'editing.save', keys: null }], overrides: {} },
            });
        });

        it('records Alt+, on French AZERTY as the Flow settings key, not the Domain key', () => {
            setUp();
            openModal();
            startAdding();

            pickAction('Save');
            record({ key: ',', code: 'KeyM', altKey: true });

            expect(feedback()).toBe(
                "Alt+, is Flow settings's key — saving moves it here; Flow settings will have no key"
            );
        });

        it('offers the flow actions in the Additional action picker', () => {
            setUp();
            openModal();
            startAdding();
            const groupTitles = Array.from(editor()!.querySelectorAll('.shortcut-picker__group-title'), text);
            expect(groupTitles[0]).toBe('Flow actions');

            pickAction('Get cURL');
            record({ key: 'j', code: 'KeyJ', altKey: true });
            click(saveButton());

            expect(customRows()).toEqual([{ label: 'Get cURL', keys: 'Alt J' }]);
            expect(nextPatch().body).toEqual({
                custom_shortcuts: { custom: [{ action: 'flow.curl', keys: 'Alt+KeyJ' }], overrides: {} },
            });
        });
    });
});
