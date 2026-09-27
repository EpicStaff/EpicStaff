import { Dialog } from '@angular/cdk/dialog';
import { formatDate } from '@angular/common';
import { TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { DATE_TIME_FORMAT_24H } from '@shared/constants';
import { NEVER, of } from 'rxjs';

import { PersistenceTable, PersistenceTableEntry } from '../../models/persistence-table.model';
import { PersistenceTablesApiService } from '../../services/persistence-tables-api.service';
import { PersistenceEntriesGridComponent } from './persistence-entries-grid.component';

const TABLE: PersistenceTable = {
    id: 1,
    name: 'profiles',
    description: '',
    entry_count: 0,
    created_at: '2026-09-24T00:00:00Z',
    updated_at: '2026-09-24T00:00:00Z',
};

function actionIcons(canUpdate: boolean, canDelete: boolean): string[] | undefined {
    TestBed.configureTestingModule({
        providers: [
            {
                provide: PersistenceTablesApiService,
                useValue: { getEntries: () => of({ count: 0, next: null, previous: null, results: [] }) },
            },
        ],
    });
    const fixture = TestBed.createComponent(PersistenceEntriesGridComponent);
    fixture.componentRef.setInput('table', TABLE);
    fixture.componentRef.setInput('canUpdate', canUpdate);
    fixture.componentRef.setInput('canDelete', canDelete);
    const actionsColumn = fixture.componentInstance.columns().find((column) => column.key === 'actions');
    return actionsColumn?.actions?.map((action) => action.icon);
}

describe('PersistenceEntriesGridComponent table switch', () => {
    it("drops the previous table's rows while the new table loads", () => {
        const entry: PersistenceTableEntry = {
            id: 7,
            table: 1,
            key: 'k',
            value: 'v',
            created_at: '2026-09-24T00:00:00Z',
            updated_at: '2026-09-24T00:00:00Z',
            updated_by_session: null,
            updated_by_graph: null,
            updated_by_graph_name: null,
        };
        TestBed.configureTestingModule({
            providers: [
                {
                    provide: PersistenceTablesApiService,
                    // Table 2's load never answers, like a slow or failed request.
                    useValue: {
                        getEntries: (params: { table: number }) =>
                            params.table === 1 ? of({ count: 1, next: null, previous: null, results: [entry] }) : NEVER,
                    },
                },
            ],
        });
        const fixture = TestBed.createComponent(PersistenceEntriesGridComponent);
        fixture.componentRef.setInput('table', TABLE);
        fixture.detectChanges();
        expect(fixture.componentInstance.entries()).toEqual([entry]);

        fixture.componentRef.setInput('table', { ...TABLE, id: 2, name: 'orders' });
        fixture.detectChanges();

        expect(fixture.componentInstance.entries()).toEqual([]);
        expect(fixture.componentInstance.totalCount()).toBe(0);
    });
});

describe('PersistenceEntriesGridComponent permission gating', () => {
    it('offers only edit with update permission only', () => {
        expect(actionIcons(true, false)).toEqual(['edit']);
    });

    it('offers only delete with delete permission only', () => {
        expect(actionIcons(false, true)).toEqual(['trash']);
    });

    it('omits the actions column without update or delete permission', () => {
        expect(actionIcons(false, false)).toBeUndefined();
    });
});

const RUN_ENTRY: PersistenceTableEntry = {
    id: 11,
    table: 1,
    key: 'profile_42',
    value: { plan: 'pro' },
    created_at: '2026-09-27T12:00:00Z',
    // Midday UTC, so the calendar day is the same in every test-runner timezone.
    updated_at: '2026-09-27T12:00:00Z',
    updated_by_session: 123,
    updated_by_graph: 5,
    updated_by_graph_name: 'Customer onboarding',
};
const HAND_EDITED_ENTRY: PersistenceTableEntry = {
    ...RUN_ENTRY,
    id: 12,
    key: 'manual',
    updated_by_session: null,
    updated_by_graph: null,
    updated_by_graph_name: null,
};

function renderGrid(options: { canUpdate?: boolean; entries?: PersistenceTableEntry[]; searchTerm?: string } = {}) {
    const getEntries = vi.fn((query: { table: number; search: string; offset: number }) => {
        const results = query.table === 1 ? (options.entries ?? [RUN_ENTRY, HAND_EDITED_ENTRY]) : [];
        return of({ count: results.length, next: null, previous: null, results });
    });
    const dialogOpen = vi.fn(() => ({ closed: NEVER }));
    TestBed.configureTestingModule({
        providers: [
            provideRouter([]),
            { provide: PersistenceTablesApiService, useValue: { getEntries } },
            { provide: Dialog, useValue: { open: dialogOpen } },
        ],
    });
    const fixture = TestBed.createComponent(PersistenceEntriesGridComponent);
    fixture.componentRef.setInput('table', TABLE);
    fixture.componentRef.setInput('canUpdate', options.canUpdate ?? false);
    fixture.componentRef.setInput('searchTerm', options.searchTerm ?? '');
    fixture.detectChanges();
    const element = fixture.nativeElement as HTMLElement;
    return { fixture, element, getEntries, dialogOpen };
}

describe('PersistenceEntriesGridComponent session column', () => {
    it('has its own "Session" column', () => {
        const { fixture } = renderGrid();
        const labels = fixture.componentInstance.columns().map((column) => column.label);
        expect(labels).toEqual(['Key', 'Value', 'Session', 'Updated']);
    });

    it('links a run-written entry to its session as "<Flow name>, Session #<id>"', () => {
        const { element } = renderGrid({ entries: [RUN_ENTRY] });
        const link = element.querySelector<HTMLAnchorElement>('a.entries-grid__session-link');
        expect(link?.textContent?.trim()).toBe('Customer onboarding, Session #123');
        expect(link?.getAttribute('href')).toBe('/graph/5/session/123');
        expect(link?.title).toBe('Customer onboarding, Session #123');
    });

    it('shows a muted dash for a hand-edited entry', () => {
        const { element } = renderGrid({ entries: [HAND_EDITED_ENTRY] });
        expect(element.querySelector('a.entries-grid__session-link')).toBeNull();
        expect(element.querySelector('.entries-grid__no-session')?.textContent?.trim()).toBe('—');
    });
});

describe('PersistenceEntriesGridComponent updated column', () => {
    it('uses the app date-time format ("Sep 27, 2026, HH:mm:ss")', () => {
        const { element } = renderGrid({ entries: [RUN_ENTRY] });
        const text = element.querySelector('.entries-grid__updated')?.textContent?.trim();
        expect(text).toBe(formatDate(RUN_ENTRY.updated_at, DATE_TIME_FORMAT_24H, 'en-US'));
        expect(text).toMatch(/^Sep 27, 2026, \d{2}:\d{2}:\d{2}$/);
    });
});

describe('PersistenceEntriesGridComponent value double-click', () => {
    it('opens the edit dialog for that entry when the user can update', () => {
        const { element, dialogOpen } = renderGrid({ canUpdate: true, entries: [RUN_ENTRY] });
        element.querySelector('.entries-grid__preview')?.dispatchEvent(new MouseEvent('dblclick', { bubbles: true }));
        expect(dialogOpen).toHaveBeenCalledOnce();
        expect(dialogOpen.mock.calls[0]).toEqual([
            expect.anything(),
            expect.objectContaining({ data: { tableId: 1, entry: RUN_ENTRY } }),
        ]);
    });

    it('hints at double-click only for users who can update', () => {
        const editable = renderGrid({ canUpdate: true, entries: [RUN_ENTRY] });
        expect(editable.element.querySelector<HTMLElement>('.entries-grid__preview')?.title).toBe(
            'Double-click to edit'
        );
        TestBed.resetTestingModule();
        const readOnly = renderGrid({ canUpdate: false, entries: [RUN_ENTRY] });
        expect(readOnly.element.querySelector('.entries-grid__preview')?.hasAttribute('title')).toBe(false);
    });

    it('clears the word the double-click selected', () => {
        const removeAllRanges = vi.fn();
        vi.spyOn(window, 'getSelection').mockReturnValue({ removeAllRanges } as unknown as Selection);
        const { element } = renderGrid({ canUpdate: true, entries: [RUN_ENTRY] });
        element.querySelector('.entries-grid__preview')?.dispatchEvent(new MouseEvent('dblclick', { bubbles: true }));
        expect(removeAllRanges).toHaveBeenCalledOnce();
        vi.restoreAllMocks();
    });

    it('does nothing without update permission', () => {
        const { element, dialogOpen } = renderGrid({ canUpdate: false, entries: [RUN_ENTRY] });
        element.querySelector('.entries-grid__preview')?.dispatchEvent(new MouseEvent('dblclick', { bubbles: true }));
        expect(dialogOpen).not.toHaveBeenCalled();
    });
});

describe('PersistenceEntriesGridComponent key search', () => {
    afterEach(() => vi.useRealTimers());

    it('has no search box of its own', () => {
        const { element } = renderGrid();
        expect(element.querySelector('app-search')).toBeNull();
    });

    it('queries a term already typed on mount straight away, without an unfiltered first load', () => {
        vi.useFakeTimers();
        const { getEntries } = renderGrid({ searchTerm: ' profile ' });

        expect(getEntries.mock.calls[0][0]).toEqual(expect.objectContaining({ table: 1, search: 'profile' }));
        expect(getEntries.mock.calls.every(([query]) => query.search === 'profile')).toBe(true);
    });

    it('sends the settled search term to the server and keeps it across a table switch', () => {
        vi.useFakeTimers();
        const { fixture, getEntries } = renderGrid();

        fixture.componentRef.setInput('searchTerm', '  profile ');
        fixture.detectChanges();
        vi.advanceTimersByTime(299);
        fixture.detectChanges();
        expect(getEntries).not.toHaveBeenCalledWith(expect.objectContaining({ search: 'profile' }));

        vi.advanceTimersByTime(1);
        fixture.detectChanges();
        expect(getEntries).toHaveBeenLastCalledWith(expect.objectContaining({ table: 1, search: 'profile' }));

        fixture.componentRef.setInput('table', { ...TABLE, id: 2, name: 'orders' });
        fixture.detectChanges();
        expect(getEntries).toHaveBeenLastCalledWith(
            expect.objectContaining({ table: 2, search: 'profile', offset: 0 })
        );
    });

    it('applies a cleared term at once', () => {
        vi.useFakeTimers();
        const { fixture, getEntries } = renderGrid({ searchTerm: 'profile' });

        fixture.componentRef.setInput('searchTerm', '');
        fixture.detectChanges();
        expect(getEntries).toHaveBeenLastCalledWith(expect.objectContaining({ search: '' }));
    });
});

describe('PersistenceEntriesGridComponent copy value', () => {
    let writeText: ReturnType<typeof vi.fn>;

    beforeEach(() => {
        writeText = vi.fn(() => Promise.resolve());
        // jsdom has no Clipboard API.
        Object.defineProperty(navigator, 'clipboard', { value: { writeText }, configurable: true });
    });
    afterEach(() => Reflect.deleteProperty(navigator, 'clipboard'));

    function copyButtons(element: HTMLElement): HTMLButtonElement[] {
        return [...element.querySelectorAll<HTMLButtonElement>('app-copy-button button')];
    }

    it('copies an object value as indented JSON, for read-only users too', () => {
        const { element } = renderGrid({ canUpdate: false, entries: [RUN_ENTRY] });
        copyButtons(element)[0].click();
        expect(writeText).toHaveBeenCalledWith('{\n  "plan": "pro"\n}');
    });

    it('copies a string value as its raw text, without JSON quotes', () => {
        const { element } = renderGrid({ entries: [{ ...RUN_ENTRY, value: 'hello "world"' }] });
        copyButtons(element)[0].click();
        expect(writeText).toHaveBeenCalledWith('hello "world"');
    });

    it('does not open the editor when Copy is double-clicked', () => {
        const { element, dialogOpen } = renderGrid({ canUpdate: true, entries: [RUN_ENTRY] });
        element.querySelector('app-copy-button')?.dispatchEvent(new MouseEvent('dblclick', { bubbles: true }));
        expect(dialogOpen).not.toHaveBeenCalled();
    });
});

describe('PersistenceEntriesGridComponent editable value hint', () => {
    it('marks the value cell editable and shows a pencil only for users who can update', () => {
        const editable = renderGrid({ canUpdate: true, entries: [RUN_ENTRY] });
        expect(editable.element.querySelector('.entries-grid__value--editable')).not.toBeNull();
        expect(editable.element.querySelector('.entries-grid__edit-hint')).not.toBeNull();
        TestBed.resetTestingModule();

        const readOnly = renderGrid({ canUpdate: false, entries: [RUN_ENTRY] });
        expect(readOnly.element.querySelector('.entries-grid__value')).not.toBeNull();
        expect(readOnly.element.querySelector('.entries-grid__value--editable')).toBeNull();
        expect(readOnly.element.querySelector('.entries-grid__edit-hint')).toBeNull();
    });
});

describe('PersistenceEntriesGridComponent sorting', () => {
    function sortHeader(element: HTMLElement, label: string): HTMLElement | undefined {
        return [...element.querySelectorAll<HTMLElement>('.col-label-group--clickable')].find(
            (header) => header.querySelector('.col-label')?.textContent?.trim() === label
        );
    }

    it('sorts by key ascending by default', () => {
        const { getEntries } = renderGrid();
        expect(getEntries).toHaveBeenLastCalledWith(expect.objectContaining({ ordering: 'key' }));
    });

    it('makes Key, Session and Updated sortable, but not Value', () => {
        const { element } = renderGrid();
        const labels = [...element.querySelectorAll('.col-label-group--clickable .col-label')].map((label) =>
            label.textContent?.trim()
        );
        expect(labels).toEqual(['Key', 'Session', 'Updated']);
    });

    it('flips the sorted column and starts a new column ascending', () => {
        const { fixture, element, getEntries } = renderGrid();
        const clickHeader = (label: string) => {
            sortHeader(element, label)?.click();
            fixture.detectChanges();
        };

        clickHeader('Key');
        expect(getEntries).toHaveBeenLastCalledWith(expect.objectContaining({ ordering: '-key' }));
        clickHeader('Updated');
        expect(getEntries).toHaveBeenLastCalledWith(expect.objectContaining({ ordering: 'updated_at' }));
        clickHeader('Updated');
        expect(getEntries).toHaveBeenLastCalledWith(expect.objectContaining({ ordering: '-updated_at' }));
        clickHeader('Session');
        expect(getEntries).toHaveBeenLastCalledWith(expect.objectContaining({ ordering: 'session' }));
    });

    it('shows the direction on the sorted column only', () => {
        const { fixture } = renderGrid();
        const icons = () =>
            fixture.componentInstance
                .columns()
                .filter((column) => column.headerIcon)
                .map((column) => [column.key, column.headerIcon, column.headerIconActive]);

        expect(icons()).toEqual([
            ['key', 'arrow-up', true],
            ['session_label', 'arrow-up-down', false],
            ['updated_at', 'arrow-up-down', false],
        ]);
        fixture.componentInstance.onSortToggle('key');
        expect(icons()[0]).toEqual(['key', 'arrow-down', true]);
    });

    it('exposes the current sort as aria-sort on the sorted header only', () => {
        const { fixture, element } = renderGrid();
        const sortedLabels = () =>
            [...element.querySelectorAll('[aria-sort]')].map((cell) => [
                cell.querySelector('.col-label')?.textContent?.trim(),
                cell.getAttribute('aria-sort'),
            ]);
        expect(sortedLabels()).toEqual([['Key', 'ascending']]);

        sortHeader(element, 'Updated')?.click();
        sortHeader(element, 'Updated')?.click();
        fixture.detectChanges();
        expect(sortedLabels()).toEqual([['Updated', 'descending']]);
    });

    it('ignores a click on a column that does not sort', () => {
        const { fixture } = renderGrid();
        fixture.componentInstance.onSortToggle('preview');
        expect(fixture.componentInstance.ordering()).toBe('key');
    });

    it('goes back to page 1 on a sort change and keeps the search term', () => {
        const entries = Array.from({ length: 20 }, (_, index) => ({ ...RUN_ENTRY, id: index + 1 }));
        const { fixture, getEntries } = renderGrid({ entries, searchTerm: 'profile' });
        fixture.componentInstance.page.set(2);
        fixture.detectChanges();
        expect(getEntries).toHaveBeenLastCalledWith(expect.objectContaining({ offset: 20 }));

        fixture.componentInstance.onSortToggle('updated_at');
        fixture.detectChanges();
        expect(fixture.componentInstance.page()).toBe(1);
        expect(getEntries).toHaveBeenLastCalledWith(
            expect.objectContaining({ ordering: 'updated_at', search: 'profile', offset: 0 })
        );
    });
});
