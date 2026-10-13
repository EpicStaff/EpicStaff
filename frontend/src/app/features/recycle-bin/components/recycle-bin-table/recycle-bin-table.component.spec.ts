import { DatePipe } from '@angular/common';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { MatTooltip } from '@angular/material/tooltip';
import { By } from '@angular/platform-browser';
import { FetchErrorStateComponent, FlowNodeListComponent, SelectComponent } from '@shared/components';
import { NodeType, UserSummary } from '@shared/models';

import { RECYCLE_BIN_DATE_FORMAT } from '../../constants/recycle-bin-dates.constants';
import { RecycleBinItem } from '../../models/recycle-bin.model';
import { RecycleBinTableComponent } from './recycle-bin-table.component';

// jsdom has no ResizeObserver; the fetch error state's overflow directive only needs it to exist.
class ResizeObserverStub {
    observe(): void {}
    unobserve(): void {}
    disconnect(): void {}
}

function binItem(overrides: Partial<RecycleBinItem>): RecycleBinItem {
    const name = overrides.name ?? 'Writer';
    return {
        key: 'agent-1',
        id: 1,
        source: 'agent',
        name,
        displayName: name,
        kind: 'Agent',
        deletedAt: new Date('2026-10-01T10:00:00Z'),
        daysLeft: 5,
        details: [],
        contents: [],
        contentsTotal: 0,
        ...overrides,
    };
}

const FLOW = binItem({
    key: 'flow-2',
    id: 2,
    source: 'flow',
    name: 'Report flow',
    kind: 'Flow',
    contents: [
        { name: 'Parse', nodeType: NodeType.PYTHON },
        { name: 'Write', nodeType: NodeType.AGENT },
    ],
    contentsTotal: 2,
});
const AGENT = binItem({});

describe('RecycleBinTableComponent', () => {
    let fixture: ComponentFixture<RecycleBinTableComponent>;

    beforeEach(() => vi.stubGlobal('ResizeObserver', ResizeObserverStub));
    afterEach(() => vi.unstubAllGlobals());

    function render(inputs: Record<string, unknown>): HTMLElement {
        fixture = TestBed.createComponent(RecycleBinTableComponent);
        fixture.componentRef.setInput('items', [FLOW, AGENT]);
        fixture.componentRef.setInput('status', 'loaded');
        fixture.componentRef.setInput('pluralNoun', 'flows');
        for (const [name, value] of Object.entries(inputs)) fixture.componentRef.setInput(name, value);
        fixture.detectChanges();
        return fixture.nativeElement as HTMLElement;
    }

    /** Renders with every row open, as a row's contents render only once it has been opened. */
    function renderOpen(inputs: Record<string, unknown>): HTMLElement {
        const items = (inputs['items'] as RecycleBinItem[] | undefined) ?? [FLOW, AGENT];
        return render({ expandedKeys: new Set(items.map((item) => item.key)), ...inputs });
    }

    function headerCells(element: HTMLElement): string[] {
        return Array.from(
            element.querySelectorAll('.table-header .col-label'),
            (cell) => cell.textContent?.trim() ?? ''
        );
    }

    function bodyRows(element: HTMLElement): HTMLElement[] {
        return Array.from(element.querySelectorAll<HTMLElement>('.bin-row-wrapper'));
    }

    it('hides both buttons and the Actions column without CREATE and DELETE', () => {
        const element = render({ canRestore: false, canPurge: false });
        expect(element.querySelector('app-activate-button')).toBeNull();
        expect(element.querySelector('app-delete-button')).toBeNull();
        expect(headerCells(element)).not.toContain('Actions');
    });

    it('shows only Restore with CREATE', () => {
        const element = render({ canRestore: true, canPurge: false });
        expect(element.querySelectorAll('app-activate-button').length).toBe(2);
        expect(element.querySelector('app-delete-button')).toBeNull();
        expect(headerCells(element)).toContain('Actions');
    });

    it('shows only Delete permanently with DELETE', () => {
        const element = render({ canRestore: false, canPurge: true });
        expect(element.querySelectorAll('app-delete-button').length).toBe(2);
        expect(element.querySelector('app-activate-button')).toBeNull();
    });

    it('emits Restore for the row without expanding it', () => {
        const element = render({ canRestore: true });
        const restoreSpy = vi.fn();
        fixture.componentInstance.restoreRequested.subscribe(restoreSpy);

        element.querySelector<HTMLButtonElement>('app-activate-button button')?.click();
        fixture.detectChanges();

        expect(restoreSpy).toHaveBeenCalledWith(FLOW);
        expect(element.querySelector('.bin-expansion')?.classList).not.toContain('expanded');
    });

    it('expands and collapses a flow row through its name button, flipping aria-expanded', () => {
        const element = render({});
        const toggle = bodyRows(element)[0].querySelector<HTMLButtonElement>('button.bin-name')!;
        expect(toggle.getAttribute('aria-expanded')).toBe('false');

        toggle.click();
        fixture.detectChanges();
        const nodeList = fixture.debugElement.query(By.directive(FlowNodeListComponent));
        expect(nodeList.componentInstance.expanded()).toBe(true);
        expect(toggle.getAttribute('aria-expanded')).toBe('true');

        toggle.click();
        fixture.detectChanges();
        expect(nodeList.componentInstance.expanded()).toBe(false);
        expect(toggle.getAttribute('aria-expanded')).toBe('false');
    });

    // jsdom can't measure layout. This guards the structure the 0-height collapse relies on: the
    // collapsing grid child must be the padding-free __clip, with the padded __inner inside it.
    it('renders a collapsed node list whose collapsing child carries no padding', () => {
        const element = renderOpen({});
        fixture.componentRef.setInput('expandedKeys', new Set());
        fixture.detectChanges();
        const list = bodyRows(element)[0].querySelector<HTMLElement>('.flow-node-list')!;
        expect(list.classList).toContain('grid-collapsible');
        expect(list.classList).not.toContain('expanded');
        expect(list.firstElementChild?.classList).toContain('flow-node-list__clip');
        expect(list.firstElementChild?.firstElementChild?.classList).toContain('flow-node-list__inner');
    });

    it('renders nothing inside a closed row until it is first opened, and keeps it after closing', () => {
        const element = render({});
        const expansion = bodyRows(element)[0].querySelector<HTMLElement>('.bin-expansion')!;
        const toggle = bodyRows(element)[0].querySelector<HTMLButtonElement>('button.bin-name')!;
        // The animated wrappers are there from the start, so the first opening animates too.
        expect(expansion.querySelector('.bin-expansion__clip')?.children.length).toBe(0);
        expect(element.querySelector('app-flow-node-list')).toBeNull();

        toggle.click();
        fixture.detectChanges();
        expect(expansion.classList).toContain('expanded');
        expect(expansion.querySelector('app-flow-node-list')).not.toBeNull();

        // Kept while it closes, so the close animation has something to shrink.
        toggle.click();
        fixture.detectChanges();
        expect(expansion.classList).not.toContain('expanded');
        expect(expansion.querySelector('app-flow-node-list')).not.toBeNull();
    });

    it('renders every row opened all at once ("Expand all"), and keeps them after "Collapse all"', () => {
        const agent = binItem({ key: 'agent-3', contents: [{ name: 'Chat', nodeType: 'surface' }], contentsTotal: 1 });
        const element = render({ items: [FLOW, agent] });
        expect(element.querySelectorAll('app-flow-node-list').length).toBe(0);

        fixture.componentRef.setInput('expandedKeys', new Set([FLOW.key, agent.key]));
        fixture.detectChanges();
        expect(element.querySelectorAll('.bin-expansion.expanded app-flow-node-list').length).toBe(2);

        fixture.componentRef.setInput('expandedKeys', new Set());
        fixture.detectChanges();
        expect(element.querySelectorAll('.bin-expansion.expanded').length).toBe(0);
        expect(element.querySelectorAll('app-flow-node-list').length).toBe(2);
    });

    it('keeps an opened row rendered when a reload or search hides it for a while', () => {
        const element = render({ expandedKeys: new Set([FLOW.key]) });
        fixture.componentRef.setInput('expandedKeys', new Set());
        fixture.componentRef.setInput('items', [AGENT]);
        fixture.detectChanges();
        expect(element.querySelector('app-flow-node-list')).toBeNull();

        fixture.componentRef.setInput('items', [{ ...FLOW }, AGENT]);
        fixture.detectChanges();
        expect(element.querySelector('app-flow-node-list')).not.toBeNull();
        expect(element.querySelector('.bin-expansion')?.classList).not.toContain('expanded');
    });

    it('makes the expand control a native, focusable button, so the keyboard can use it', () => {
        const element = render({});
        const toggle = bodyRows(element)[0].querySelector<HTMLButtonElement>('button.bin-name')!;
        expect(toggle.type).toBe('button');

        toggle.focus();
        expect(document.activeElement).toBe(toggle);
    });

    it('does not make a row without contents expandable', () => {
        const element = render({});
        const agentRow = bodyRows(element)[1];
        expect(agentRow.querySelector('.bin-collapse-icon')).toBeNull();
        expect(agentRow.querySelector('button.bin-name')).toBeNull();
        expect(agentRow.querySelector('app-flow-node-list')).toBeNull();
    });

    it('disables the buttons of a row with an action in flight', () => {
        const element = render({ canRestore: true, canPurge: true, pendingKeys: new Set(['flow-2']) });
        const [flowRow, agentRow] = bodyRows(element);
        expect(flowRow.querySelector<HTMLButtonElement>('app-activate-button button')?.disabled).toBe(true);
        expect(flowRow.querySelector<HTMLButtonElement>('app-delete-button button')?.disabled).toBe(true);
        expect(agentRow.querySelector<HTMLButtonElement>('app-activate-button button')?.disabled).toBe(false);
    });

    it('hides the Kind column by default (every row has the same kind)', () => {
        const element = render({});
        expect(headerCells(element)).toEqual(['Name', 'Deleted at', 'Days left']);
        expect(element.querySelector('.bin-kind')).toBeNull();
    });

    it('shows the Kind column when asked to', () => {
        const element = render({ showKind: true, canPurge: true });
        expect(headerCells(element)).toEqual(['Name', 'Kind', 'Deleted at', 'Days left', 'Actions']);
        const kinds = Array.from(element.querySelectorAll('.bin-kind'), (cell) => cell.textContent?.trim());
        expect(kinds).toEqual(['Flow', 'Agent']);
    });

    it('shows the deletion time relative, with the full date in its tooltip', () => {
        const deletedAt = new Date(Date.now() - 2 * 60 * 60 * 1000);
        const element = render({ items: [binItem({ deletedAt })] });
        const cell = fixture.debugElement.query(By.css('.bin-deleted'));
        expect(element.querySelector('.bin-deleted')?.textContent?.trim()).toBe('2h ago');
        expect(cell.injector.get(MatTooltip).message).toBe(
            new DatePipe('en-US').transform(deletedAt, RECYCLE_BIN_DATE_FORMAT)
        );
    });

    it('sorts by the date columns, always with their arrow; Name has no sort', () => {
        const element = render({});
        const arrows = Array.from(
            element.querySelectorAll('.table-header .sort-header'),
            (header) => header.querySelector('.sort-header__icon') !== null
        );
        expect(arrows).toEqual([true, true]);
        expect(element.querySelector('.table-header .table-cell:not(.checkbox) .col-label')?.textContent?.trim()).toBe(
            'Name'
        );
    });

    it('shows a spinner while loading', () => {
        const element = render({ status: 'loading' });
        expect(element.querySelector('app-loading-spinner')).not.toBeNull();
    });

    it('shows the fetch error state and asks for a retry', () => {
        render({ status: 'error' });
        const retrySpy = vi.fn();
        fixture.componentInstance.retryRequested.subscribe(retrySpy);

        const errorState = fixture.debugElement.query(By.directive(FetchErrorStateComponent));
        expect(errorState).not.toBeNull();
        (errorState.componentInstance as FetchErrorStateComponent).retry.emit();
        expect(retrySpy).toHaveBeenCalled();
    });

    it('names the retention time in the empty state', () => {
        const element = render({ items: [], retentionDays: 7 });
        expect(element.textContent).toContain('The recycle bin is empty');
        expect(element.textContent).toContain('Deleted flows stay here for 7 days.');
    });

    it('labels the days left', () => {
        const element = render({
            items: [
                binItem({ key: 'agent-1', daysLeft: 0 }),
                binItem({ key: 'agent-2', daysLeft: 1 }),
                binItem({ key: 'agent-3', daysLeft: 5 }),
            ],
        });
        const labels = Array.from(element.querySelectorAll('.bin-days-left'), (cell) => cell.textContent?.trim());
        expect(labels).toEqual(['Today', '1 day', '5 days']);
    });

    it('shows the paginator only when there is more than one page', () => {
        let element = render({ page: { current: 1, size: 50, totalCount: 50 } });
        expect(element.querySelector('app-pagination-controls')).toBeNull();

        element = render({ page: { current: 1, size: 50, totalCount: 51 } });
        expect(element.querySelector('app-pagination-controls')).not.toBeNull();
    });

    it('offers "Show all" when the backend listed only part of the contents, and asks for the rest', () => {
        const folder = binItem({
            key: 'storage-9',
            source: 'storage',
            name: 'docs/',
            kind: 'Folder',
            contents: [{ name: 'a.txt', nodeType: 'file' }],
            contentsTotal: 2301,
        });
        const element = renderOpen({ items: [folder] });
        const requested = vi.fn();
        fixture.componentInstance.showAllRequested.subscribe(requested);

        const showAll = element.querySelector<HTMLButtonElement>('.flow-node-list__more--action');
        expect(showAll?.textContent?.trim()).toBe('Show all 2,301');
        showAll!.click();
        expect(requested).toHaveBeenCalledWith(folder);
    });

    it('has no "more" line when every content is listed', () => {
        const element = renderOpen({});
        expect(element.querySelector('.flow-node-list__more')).toBeNull();
    });

    it('filters an opened row by the tab search only when the match is inside it', () => {
        const byName = binItem({
            key: 'flow-1',
            displayName: 'Marketing flow',
            contents: [{ name: 'Start', nodeType: 'start' }],
            contentsTotal: 1,
        });
        const byContent = binItem({
            key: 'flow-2',
            displayName: 'Nightly',
            contents: [
                { name: 'Send marketing mail', nodeType: 'task' },
                { name: 'Archive', nodeType: 'task' },
            ],
            contentsTotal: 2,
        });
        const element = render({ items: [byName, byContent], searchTerm: 'marketing' });
        element.querySelectorAll<HTMLButtonElement>('button.bin-name').forEach((button) => button.click());
        fixture.detectChanges();

        const lists = element.querySelectorAll('app-flow-node-list');
        const names = (list: Element): string[] =>
            Array.from(list.querySelectorAll('.flow-node-list__node-name'), (name) => name.textContent?.trim() ?? '');
        expect(names(lists[0])).toEqual(['Start']);
        expect(names(lists[1])).toEqual(['Send marketing mail']);
    });

    it('stops offering "Show all" once a row holds the most it can load', () => {
        render({});
        const table = fixture.componentInstance;
        const holding = (count: number): RecycleBinItem =>
            binItem({
                contents: Array.from({ length: count }, (_, index) => ({ name: `f${index}`, nodeType: 'file' })),
            });

        // Checked on the component: rendering 5,000 rows here would take seconds.
        expect(table['canShowAll'](holding(100))).toBe(true);
        expect(table['canShowAll'](holding(5000))).toBe(false);
    });

    it('counts the keys of a key-value table in their column but lists none', () => {
        const table = binItem({ key: 'key_value_table-3', source: 'key_value_table', contentsTotal: 4 });
        const element = render({ items: [table], countLabel: 'Keys' });

        expect(element.querySelector('.bin-count')?.textContent?.trim()).toBe('4');
        expect(element.querySelector('app-flow-node-list')).toBeNull();
        expect(element.querySelector('button.bin-name')).toBeNull();
    });

    it('offers a search inside a row only when it holds more than one item', () => {
        const one = binItem({ key: 'agent-1', contents: [{ name: 'Chat', nodeType: 'surface' }], contentsTotal: 1 });
        const two = binItem({
            key: 'agent-2',
            contents: [
                { name: 'Chat', nodeType: 'surface' },
                { name: 'Mail', nodeType: 'surface' },
            ],
            contentsTotal: 2,
        });
        const element = renderOpen({ items: [one, two] });
        const lists = element.querySelectorAll('app-flow-node-list');

        expect(lists[0].querySelector('app-search')).toBeNull();
        expect(lists[1].querySelector('app-search')).not.toBeNull();
    });

    it('expands a row from anywhere on it, but not from its checkbox', () => {
        const agent = binItem({ contents: [{ name: 'Support chat', nodeType: 'surface' }], contentsTotal: 1 });
        const element = render({ items: [agent], selectable: true });
        const expansion = (): Element | null => element.querySelector('.bin-expansion');

        element.querySelector<HTMLInputElement>('.table-row app-checkbox input')!.click();
        fixture.detectChanges();
        expect(expansion()?.classList).not.toContain('expanded');

        element.querySelector<HTMLElement>('.bin-deleted')!.click();
        fixture.detectChanges();
        expect(expansion()?.classList).toContain('expanded');

        element.querySelector<HTMLButtonElement>('button.bin-name')!.click();
        fixture.detectChanges();
        expect(expansion()?.classList).not.toContain('expanded');
    });

    it('expands a non-flow row and shows its contents with readable kinds', () => {
        const agent = binItem({ contents: [{ name: 'Support chat', nodeType: 'surface' }], contentsTotal: 1 });
        const element = render({ items: [agent] });

        element.querySelector<HTMLButtonElement>('button.bin-name')?.click();
        fixture.detectChanges();

        const list = element.querySelector('.flow-node-list');
        expect(list?.classList).toContain('expanded');
        expect(list?.querySelector('.flow-node-list__node-name')?.textContent?.trim()).toBe('Support chat');
        expect(list?.querySelector('.flow-node-list__node-type')?.textContent?.trim()).toBe('Surface');
        // The sprite icon the agents page draws surfaces with, not a font icon.
        expect(list?.querySelector('.flow-node-list__svg-icon')).not.toBeNull();
        expect(list?.querySelector('i')).toBeNull();
    });

    it('makes a row with details but no contents expandable (a tool)', () => {
        const tool = binItem({
            key: 'python_tool-3',
            source: 'python_tool',
            details: [{ label: 'Description', format: 'text', value: 'Parses PDFs' }],
        });
        const element = render({ items: [tool] });

        element.querySelector<HTMLButtonElement>('button.bin-name')?.click();
        fixture.detectChanges();

        expect(element.querySelector('.bin-expansion')?.classList).toContain('expanded');
        expect(element.querySelector('.bin-details__value')?.textContent?.trim()).toBe('Parses PDFs');
        expect(element.querySelector('app-flow-node-list')).toBeNull();
    });

    it('formats a date detail to the minute (no seconds) and a size detail as a file size', () => {
        const created = new Date('2026-09-01T08:00:00Z');
        const file = binItem({
            key: 'storage-12',
            source: 'storage',
            details: [
                { label: 'Created', format: 'date', value: created },
                { label: 'Size', format: 'size', value: 1536 },
            ],
        });
        const element = renderOpen({ items: [file] });

        const values = Array.from(element.querySelectorAll('.bin-details__value'), (cell) => cell.textContent?.trim());
        expect(values).toEqual([new DatePipe('en-US').transform(created, RECYCLE_BIN_DATE_FORMAT), '2 KB']);
        expect(values[0]).not.toMatch(/:\d\d:\d\d/);
    });

    it('puts the details above the contents', () => {
        const agent = binItem({
            details: [{ label: 'Description', format: 'text', value: 'Answers support mail' }],
            contents: [{ name: 'Support chat', nodeType: 'surface' }],
            contentsTotal: 1,
        });
        const element = renderOpen({ items: [agent] });

        const clip = element.querySelector('.bin-expansion > .bin-expansion__clip');
        const blocks = Array.from(clip?.children ?? [], (child) => child.tagName.toLowerCase());
        expect(blocks).toEqual(['dl', 'app-flow-node-list']);
    });

    it('labels the kind filter "Select kind" outside flows, and keeps the node wording for flows', () => {
        const agent = binItem({
            key: 'agent-7',
            contents: [{ name: 'Support chat', nodeType: 'surface' }],
            contentsTotal: 1,
        });
        renderOpen({ items: [FLOW, agent] });

        const lists = fixture.debugElement.queryAll(By.directive(FlowNodeListComponent));
        expect(lists.map((list) => list.componentInstance.filterPlaceholder())).toEqual([
            'Select node type',
            'Select kind',
        ]);
    });

    it('shows an empty detail as a muted dash', () => {
        const tool = binItem({
            key: 'python_tool-4',
            source: 'python_tool',
            details: [{ label: 'Description', format: 'empty', value: null }],
        });
        const element = renderOpen({ items: [tool] });
        expect(element.querySelector('.bin-details__value .bin-details__empty')?.textContent?.trim()).toBe('—');
    });

    describe('user details', () => {
        const IVAN: UserSummary = { id: 1, display_name: 'Ivan Bohun', avatar_url: 'https://example.com/ivan.png' };
        const UNNAMED: UserSummary = { id: 2, display_name: null, avatar_url: null };

        function userRows(createdBy: UserSummary | null, deletedBy: UserSummary | null): Element[] {
            const tool = binItem({
                details: [
                    { label: 'Created by', format: 'user', value: createdBy },
                    { label: 'Deleted by', format: 'user', value: deletedBy },
                ],
            });
            const element = renderOpen({ items: [tool] });
            return Array.from(element.querySelectorAll('.bin-details__row'));
        }

        it('shows the avatar and the name of a user', () => {
            const [created] = userRows(IVAN, IVAN);

            expect(created.classList).toContain('bin-details__row--user');
            expect(created.querySelector('.bin-details__label')?.textContent?.trim()).toBe('Created by');
            expect(created.querySelector('.bin-details__user-name')?.textContent?.trim()).toBe('Ivan Bohun');
            expect(created.querySelector('app-user-avatar img')?.getAttribute('src')).toBe(
                'https://example.com/ivan.png'
            );
        });

        it('shows an unknown user as a muted "Unknown", without an avatar', () => {
            const [, deleted] = userRows(IVAN, null);

            expect(deleted.classList).toContain('bin-details__row--user');
            expect(deleted.querySelector('.bin-details__user .bin-details__empty')?.textContent?.trim()).toBe(
                'Unknown'
            );
            expect(deleted.querySelector('app-user-avatar')).toBeNull();
        });

        it('shows "Unnamed user" with the placeholder avatar for a user without a display name', () => {
            const [created] = userRows(UNNAMED, IVAN);

            expect(created.querySelector('.bin-details__user-name')?.textContent?.trim()).toBe('Unnamed user');
            const avatar = created.querySelector('app-user-avatar');
            expect(avatar).not.toBeNull();
            expect(avatar?.querySelector('img')).toBeNull();
            expect(avatar?.querySelector('app-svg-icon')).not.toBeNull();
        });

        it('leaves the other formats as they were around the user lines', () => {
            const created = new Date('2026-09-01T08:00:00Z');
            const file = binItem({
                details: [
                    { label: 'Created by', format: 'user', value: IVAN },
                    { label: 'Deleted by', format: 'user', value: null },
                    { label: 'Description', format: 'text', value: 'Quarterly report' },
                    { label: 'Created', format: 'date', value: created },
                    { label: 'Size', format: 'size', value: 1536 },
                    { label: 'Folder', format: 'empty', value: null },
                    { label: 'Comes back to', format: 'notice', value: 'A new docs/ folder' },
                ],
            });
            const element = renderOpen({ items: [file] });

            const rows = Array.from(element.querySelectorAll('.bin-details__row'));
            expect(rows.map((row) => row.querySelector('.bin-details__value')?.textContent?.trim())).toEqual([
                'Ivan Bohun',
                'Unknown',
                'Quarterly report',
                new DatePipe('en-US').transform(created, RECYCLE_BIN_DATE_FORMAT),
                '2 KB',
                '—',
                'A new docs/ folder',
            ]);
            expect(rows[2].querySelector('.bin-details__text')).not.toBeNull();
            expect(rows[5].querySelector('.bin-details__empty')).not.toBeNull();
            expect(rows[6].classList).toContain('bin-details__row--notice');
            expect(rows.slice(2).some((row) => row.classList.contains('bin-details__row--user'))).toBe(false);
            expect(rows.slice(2).some((row) => row.querySelector('app-user-avatar'))).toBe(false);
        });
    });

    it('shows a storage row by its own name', () => {
        const file = binItem({
            key: 'storage-5',
            source: 'storage',
            name: 'docs/reports/report.pdf',
            displayName: 'report.pdf',
        });
        const element = render({ items: [file] });
        expect(element.querySelector('.bin-name-text')?.textContent?.trim()).toBe('report.pdf');
    });

    it('labels an expanded folder\u2019s contents by file format, without a filter', () => {
        const folder = binItem({
            key: 'storage-6',
            source: 'storage',
            name: 'docs/',
            displayName: 'docs/',
            contents: [
                { name: 'a.pdf', nodeType: 'file' },
                { name: 'sub/', nodeType: 'folder' },
                { name: 'sub/b.md', nodeType: 'file' },
                { name: 'c.pdf', nodeType: 'file' },
            ],
            contentsTotal: 4,
        });
        const element = renderOpen({ items: [folder] });

        const labels = Array.from(element.querySelectorAll('.flow-node-list__node-type'), (label) =>
            label.textContent?.trim()
        );
        expect(labels).toEqual(['PDF', 'Folder', 'MD', 'PDF']);
        // A folder shows as a tree, so it has no filter.
        expect(element.querySelector('.flow-node-list__toolbar app-select')).toBeNull();
    });

    it('uses the refresh (two arrows) icon on the Restore button', () => {
        const element = render({ canRestore: true });
        expect(element.querySelector('app-activate-button use')?.getAttribute('href')).toBe('#icon-refresh');
    });

    it('lets the details and contents blocks sit flush, without the list margin', () => {
        const agent = binItem({
            details: [{ label: 'Description', format: 'text', value: 'x' }],
            contents: [{ name: 'Support chat', nodeType: 'surface' }],
            contentsTotal: 1,
        });
        const element = renderOpen({ items: [agent] });
        expect(element.querySelector('.flow-node-list')?.classList).toContain('flow-node-list--flush');
    });

    function filterIn(element: HTMLElement, rowIndex: number): Element | null {
        return bodyRows(element)[rowIndex].querySelector('.flow-node-list__toolbar app-select');
    }

    it('hides the kind filter when every content has the same kind, and keeps the search', () => {
        const agent = binItem({
            contents: [
                { name: 'Support chat', nodeType: 'surface' },
                { name: 'Sales chat', nodeType: 'surface' },
            ],
            contentsTotal: 2,
        });
        const element = renderOpen({ items: [agent] });
        expect(filterIn(element, 0)).toBeNull();
        expect(bodyRows(element)[0].querySelector('.flow-node-list__toolbar app-search')).not.toBeNull();
    });

    it('shows the kind filter when the contents have two or more kinds', () => {
        const element = renderOpen({ items: [FLOW] });
        expect(filterIn(element, 0)).not.toBeNull();
    });

    it('shows a folder as a tree without a filter: branches start closed and open on a click', () => {
        const folder = binItem({
            key: 'storage-7',
            source: 'storage',
            name: 'docs/',
            displayName: 'docs/',
            contents: [
                { name: 'a.pdf', nodeType: 'file', key: 'a.pdf', depth: 0 },
                { name: 'sub/', nodeType: 'folder', key: 'sub/', depth: 0 },
                { name: 'b.md', nodeType: 'file', key: 'sub/b.md', depth: 1 },
            ],
            contentsTotal: 3,
        });
        const element = render({ items: [folder] });
        element.querySelector<HTMLButtonElement>('button.bin-name')?.click();
        fixture.detectChanges();
        const shownNames = (): (string | undefined)[] =>
            Array.from(element.querySelectorAll('.flow-node-list__node-name'), (name) => name.textContent?.trim());

        expect(filterIn(element, 0)).toBeNull();
        expect(shownNames()).toEqual(['a.pdf', 'sub/']);

        element.querySelector<HTMLButtonElement>('.flow-node-list__branch-toggle')?.click();
        fixture.detectChanges();
        expect(shownNames()).toEqual(['a.pdf', 'sub/', 'b.md']);

        // A click anywhere on the folder's row closes it again, like a folder in Files.
        element.querySelector<HTMLElement>('.flow-node-list__row--branch')?.click();
        fixture.detectChanges();
        expect(shownNames()).toEqual(['a.pdf', 'sub/']);
    });

    function collection(key: string, documentNames: string[]): RecycleBinItem {
        return binItem({
            key,
            source: 'collection',
            name: key,
            contents: documentNames.map((name) => ({ name, nodeType: 'document' })),
            contentsTotal: documentNames.length,
        });
    }

    it('offers the document formats of a collection with mixed formats', () => {
        const element = renderOpen({ items: [collection('collection-1', ['a.pdf', 'b.docx', 'c.pdf', 'd.txt'])] });
        expect(filterIn(element, 0)).not.toBeNull();

        const list = fixture.debugElement.query(By.directive(FlowNodeListComponent));
        const options = list.componentInstance.nodeTypeFilterItems().map((option: { name: string }) => option.name);
        expect(options).toEqual(['All', 'PDF', 'DOCX', 'TXT']);
        expect(list.componentInstance.filterPlaceholder()).toBe('Select format');
        // Each item's label is its format, the same as the filter offers.
        const labels = Array.from(bodyRows(element)[0].querySelectorAll('.flow-node-list__node-type')).map((label) =>
            label.textContent?.trim()
        );
        expect(labels).toEqual(['PDF', 'DOCX', 'PDF', 'TXT']);
    });

    it('shows only the search for a collection whose documents share one format', () => {
        const element = renderOpen({ items: [collection('collection-2', ['a.pdf', 'b.pdf'])] });
        expect(filterIn(element, 0)).toBeNull();
    });

    it('has no checkbox column unless rows are selectable', () => {
        const element = render({});
        expect(element.querySelector('app-checkbox')).toBeNull();
    });

    it('emits a row toggle and the header toggle, and reflects the selection', () => {
        const element = render({ selectable: true, selectedKeys: new Set(['flow-2']) });
        const toggled = vi.fn();
        const all = vi.fn();
        fixture.componentInstance.selectionToggled.subscribe(toggled);
        fixture.componentInstance.allToggled.subscribe(all);

        const header = element.querySelector<HTMLInputElement>('.table-header app-checkbox input')!;
        expect(header.indeterminate).toBe(true);
        expect(bodyRows(element)[0].querySelector('.table-row')?.classList).toContain('selected');

        element.querySelectorAll<HTMLInputElement>('.table-row app-checkbox input')[1].click();
        expect(toggled).toHaveBeenCalledWith(AGENT);

        // With a row selected, the header checkbox clears the selection rather than selecting the rest,
        // and stays unticked.
        header.click();
        expect(all).toHaveBeenCalledWith(false);
        expect(header.checked).toBe(false);
    });

    it('selects every row with the header checkbox when none is selected', () => {
        const element = render({ selectable: true });
        const all = vi.fn();
        fixture.componentInstance.allToggled.subscribe(all);

        element.querySelector<HTMLInputElement>('.table-header app-checkbox input')!.click();

        expect(all).toHaveBeenCalledWith(true);
    });

    it('clamps a long text detail and keeps its full value for the tooltip', () => {
        const long = 'Be brief. '.repeat(60).trim();
        const tool = binItem({ details: [{ label: 'Description', format: 'text', value: long }] });
        const element = render({ items: [tool] });

        element.querySelector<HTMLButtonElement>('button.bin-name')?.click();
        fixture.detectChanges();

        const text = fixture.debugElement.query(By.css('.bin-details__text'));
        expect(text.injector.get(MatTooltip).message).toBe(long);
    });

    it('shows a notice in the accent colour without an icon, and splits a joined list with slashes', () => {
        const collection = binItem({
            details: [
                { label: 'Indexed', format: 'text', value: 'Naive RAG: Indexed · GraphRAG: Not indexed' },
                { label: 'Comes back as', format: 'notice', value: 'Shared' },
            ],
        });
        const element = render({ items: [collection] });

        element.querySelector<HTMLButtonElement>('button.bin-name')?.click();
        fixture.detectChanges();

        const rows = element.querySelectorAll('.bin-details__row');
        expect(rows[0].querySelector('.bin-details__separator')?.textContent).toBe('/');
        expect(rows[0].textContent).not.toContain('·');
        // "Comes back shared" is a notice: the accent colour, no warning icon.
        expect(rows[1].classList).toContain('bin-details__row--notice');
        expect(rows[1].querySelector('app-svg-icon')).toBeNull();
    });

    it('sorts by the two date columns only, emits the clicked one and marks the sorted one', () => {
        const element = render({ sort: { field: 'daysLeft', direction: 'asc' } });
        const sorted = vi.fn();
        fixture.componentInstance.sortRequested.subscribe(sorted);

        const headers = element.querySelectorAll<HTMLButtonElement>('.table-header .sort-header');
        expect(Array.from(headers, (header) => header.textContent?.trim())).toEqual(['Deleted at', 'Days left']);
        expect(headers[1].closest('.table-cell')?.getAttribute('aria-sort')).toBe('ascending');

        headers[0].click();
        expect(sorted).toHaveBeenCalledWith('deletedAt');
    });

    it('marks only the sorted date column; the other keeps a dimmed arrow', () => {
        const element = render({ sort: { field: 'deletedAt', direction: 'asc' } });
        const headers = element.querySelectorAll<HTMLButtonElement>('.table-header .sort-header');

        expect(headers[0].closest('.table-cell')?.getAttribute('aria-sort')).toBe('ascending');
        expect(headers[1].closest('.table-cell')?.getAttribute('aria-sort')).toBeNull();
        expect(headers[0].classList).toContain('sort-header--active');
        expect(headers[1].classList).not.toContain('sort-header--active');
        expect(headers[1].querySelector('.sort-header__icon')).not.toBeNull();
    });

    it('points each arrow its own column\u2019s way, sorted by it or not', () => {
        const element = render({
            sort: { field: 'deletedAt', direction: 'asc' },
            columnDirections: { deletedAt: 'asc', daysLeft: 'desc' },
        });
        const arrowUp = (index: number): boolean =>
            element.querySelectorAll('.table-header .sort-header')[index].querySelector('.sort-header__icon--asc') !==
            null;

        expect(arrowUp(0)).toBe(true);
        expect(arrowUp(1)).toBe(false);
    });

    it('has no header checkbox when a search or filter left nothing to select', () => {
        const element = render({ items: [], filtered: true, selectable: true });

        expect(element.querySelector('.table-header')).not.toBeNull();
        expect(element.querySelector('.table-header app-checkbox')).toBeNull();
    });

    it('names each checkbox for screen readers', () => {
        const element = render({ selectable: true });

        expect(element.querySelector('.table-header app-checkbox input')?.getAttribute('aria-label')).toBe(
            'Select all'
        );
        expect(element.querySelector('.table-row app-checkbox input')?.getAttribute('aria-label')).toMatch(/^Select /);
    });

    it('keeps the table and its filters when a search or filter matches nothing, so it can be undone', () => {
        const element = render({
            items: [],
            filtered: true,
            showKind: true,
            kindOptions: [
                { name: 'File', value: 'file' },
                { name: 'Folder', value: 'folder' },
            ],
            kindFilter: 'folder',
        });
        expect(element.querySelector('.table-header')).not.toBeNull();
        expect(element.querySelector('.table-header .col-label--filter')?.textContent).toContain('Kind');
        expect(element.querySelector('.table-body .bin-no-results')?.textContent?.trim()).toBe(
            'No items match the current search or filters.'
        );
        expect(element.textContent).not.toContain('The recycle bin is empty');
    });

    it('shows a filter on the Kind header when it has options, and emits the chosen one', () => {
        const element = render({
            showKind: true,
            kindOptions: [
                { name: 'File', value: 'file' },
                { name: 'Folder', value: 'folder' },
            ],
            kindFilter: 'folder',
        });
        const changed = vi.fn();
        fixture.componentInstance.kindFilterChanged.subscribe(changed);

        const trigger = element.querySelector('.col-label--filter');
        expect(trigger?.textContent).toContain('Kind');
        expect(trigger?.textContent).toContain('(1)');
        expect(trigger?.querySelector('app-svg-icon')).not.toBeNull();

        const select = fixture.debugElement.query(By.directive(SelectComponent));
        expect(select.componentInstance.items().map((item: { name: string }) => item.name)).toEqual([
            'All',
            'File',
            'Folder',
        ]);
        select.componentInstance.changed.emit(null);
        expect(changed).toHaveBeenCalledWith(null);
    });

    it('shows the count column with a range filter and no sort control', () => {
        const element = render({ countLabel: 'Nodes' });
        expect(headerCells(element)).toEqual(['Name', 'Nodes', 'Deleted at', 'Days left']);
        const sortTitles = Array.from(element.querySelectorAll('.sort-header'), (header) => header.textContent?.trim());
        expect(sortTitles).not.toContain('Nodes');
        const changed = vi.fn();
        fixture.componentInstance.countFilterChanged.subscribe(changed);
        const select = fixture.debugElement.query(By.directive(SelectComponent));
        expect(select.componentInstance.items().map((item: { name: string }) => item.name)).toEqual([
            'All',
            'Has',
            'Has none',
        ]);
        select.componentInstance.changed.emit('some');
        expect(changed).toHaveBeenCalledWith('some');
        expect(Array.from(element.querySelectorAll('.bin-count'), (cell) => cell.textContent?.trim())).toEqual([
            '2',
            '0',
        ]);
    });
});
