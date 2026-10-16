import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { GetMeResponse } from '@shared/models';

import { ProfileService } from '../../../../../../services/auth/profile.service';
import { ConfigService } from '../../../../../../services/config';
import { PLATFORM_IS_MAC } from '../../../../../../visual-programming/services/keymap.service';
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
    shortcut_overrides: {},
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

interface RenderedRow {
    label: string;
    chords: string[][];
}

describe('ShortcutsModalComponent', () => {
    let fixture: ComponentFixture<ShortcutsModalComponent>;
    let httpMock: HttpTestingController;

    function setUp(isMac = false): void {
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
    }

    function loadUser(overrides: Record<string, string>): void {
        TestBed.inject(ProfileService).getCurrentUser().subscribe();
        httpMock.expectOne({ method: 'GET', url: PROFILE_URL }).flush({ ...BASE_USER, shortcut_overrides: overrides });
    }

    function openModal(): void {
        fixture = TestBed.createComponent(ShortcutsModalComponent);
        fixture.componentRef.setInput('open', true);
        fixture.componentRef.setInput('pos', { top: 10, left: 10 });
        fixture.detectChanges();
    }

    function text(element: Element): string {
        return (element.textContent ?? '').trim();
    }

    function sectionTitles(): string[] {
        return Array.from(fixture.nativeElement.querySelectorAll('.shortcuts__card-title'), text);
    }

    function rowsOf(sectionTitle: string): RenderedRow[] {
        return rowElementsOf(sectionTitle).map(readRow);
    }

    function rowElementsOf(sectionTitle: string): Element[] {
        const card = Array.from(fixture.nativeElement.querySelectorAll('.shortcuts__card') as NodeListOf<Element>).find(
            (candidate) => text(candidate.querySelector('.shortcuts__card-title')!) === sectionTitle
        );
        if (!card) throw new Error(`No "${sectionTitle}" section rendered`);
        return Array.from(card.querySelectorAll('.shortcuts__row'));
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

    afterEach(() => {
        try {
            httpMock.verify();
        } finally {
            TestBed.resetTestingModule();
        }
    });

    it('shows the sections in order, Nodes last', () => {
        setUp();
        openModal();

        expect(sectionTitles()).toEqual(['Editing', 'Navigating', 'Selection', 'Zoom', 'Nodes']);
    });

    it('keeps the same height when minimized', () => {
        setUp();
        openModal();
        const modal = (): HTMLElement => fixture.nativeElement.querySelector('.shortcuts__modal');
        const height = (): string => modal().style.getPropertyValue('--shortcuts-modal-height');
        const wideHeight = height();

        fixture.nativeElement.querySelector('.shortcuts__size-btn').click();
        fixture.detectChanges();

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

    it('shows the key a user has rebound instead of the default', () => {
        setUp();
        loadUser({ 'node.python': 'Shift+KeyB' });
        openModal();

        expect(rowsOf('Nodes')[0]).toEqual({ label: 'Python Code Node', chords: [['Shift', 'B']] });
    });

    it('keeps a node listed without keys when its default key went to another node', () => {
        setUp();
        loadUser({ 'node.python': 'Shift+KeyT', 'node.agent': 'Shift+KeyP' });
        openModal();

        const nodes = rowsOf('Nodes');
        expect(nodes.find((row) => row.label === 'Python Code Node')).toEqual({
            label: 'Python Code Node',
            chords: [],
        });
        expect(nodes.find((row) => row.label === 'Agent Node')).toEqual({
            label: 'Agent Node',
            chords: [['Shift', 'P']],
        });
        expect(nodes.find((row) => row.label === 'Task Node')).toEqual({
            label: 'Task Node',
            chords: [['Shift', 'T']],
        });
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
});
