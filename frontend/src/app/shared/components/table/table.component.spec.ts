import { Component } from '@angular/core';
import { TestBed } from '@angular/core/testing';

import { AppTableComponent } from './table.component';
import { AppTableColumnDef, TableRow } from './table.model';

function renderTable(columns: AppTableColumnDef[]) {
    const fixture = TestBed.createComponent(AppTableComponent);
    fixture.componentRef.setInput('columns', columns);
    fixture.componentRef.setInput('data', [{ id: 1, name: 'a' }]);
    fixture.detectChanges();
    return { fixture, element: fixture.nativeElement as HTMLElement };
}

describe('AppTableComponent header icon', () => {
    it('renders the clickable header as a keyboard-reachable button that emits its key and anchor', () => {
        const { fixture, element } = renderTable([{ key: 'name', label: 'Name', headerIcon: 'menu' }]);
        const headerIconClick = vi.fn();
        fixture.componentInstance.headerIconClick.subscribe(headerIconClick);

        const button = element.querySelector<HTMLButtonElement>('.table-header button.col-label-group--clickable');
        expect(button?.type).toBe('button');
        button?.click();
        expect(headerIconClick).toHaveBeenCalledWith({ key: 'name', target: button });
    });

    it('sets aria-sort on the header cell only for a column that carries a sort direction', () => {
        const { element } = renderTable([
            { key: 'name', label: 'Name', headerIcon: 'arrow-up', sortDirection: 'ascending' },
            { key: 'id', label: 'Id', headerIcon: 'arrow-up-down' },
        ]);
        const cells = [...element.querySelectorAll('.table-header .table-cell')];
        expect(cells[0].getAttribute('aria-sort')).toBe('ascending');
        expect(cells[1].hasAttribute('aria-sort')).toBe(false);
    });
});

describe('AppTableComponent select all', () => {
    // Row 1 cannot be toggled but is preselected, like the current user's own membership.
    const ROWS = [
        { id: 1, name: 'locked' },
        { id: 2, name: 'b' },
        { id: 3, name: 'c' },
    ];

    function renderSelectable(initialSelectedIds: number[]) {
        const fixture = TestBed.createComponent(AppTableComponent);
        fixture.componentRef.setInput('columns', [{ key: 'name', label: 'Name' }]);
        fixture.componentRef.setInput('data', ROWS);
        fixture.componentRef.setInput('selectable', true);
        fixture.componentRef.setInput('rowSelectable', (row: { id: number }) => row.id !== 1);
        fixture.componentRef.setInput('initialSelectedIds', initialSelectedIds);
        fixture.detectChanges();
        const table = fixture.componentInstance;
        const emitted: unknown[][] = [];
        table.selectionChange.subscribe((rows) => emitted.push(rows.map((row) => row['id'])));
        const selectedIds = () => table.selectedItems().map((row) => row['id']);
        return { table, emitted, selectedIds };
    }

    it('adds the selectable rows and keeps a preselected non-selectable row', () => {
        const { table, emitted, selectedIds } = renderSelectable([1]);
        expect(table.allSelected()).toBe(false);
        expect(table.indeterminate()).toBe(false);

        table.toggleAll();

        expect(selectedIds()).toEqual([1, 2, 3]);
        expect(emitted.at(-1)).toEqual([1, 2, 3]);
        expect(table.allSelected()).toBe(true);
        expect(table.indeterminate()).toBe(false);
    });

    it('removes only the selectable rows on deselect all', () => {
        const { table, emitted, selectedIds } = renderSelectable([1, 2, 3]);
        expect(table.allSelected()).toBe(true);

        table.toggleAll();

        expect(selectedIds()).toEqual([1]);
        expect(emitted.at(-1)).toEqual([1]);
        expect(table.allSelected()).toBe(false);
        expect(table.indeterminate()).toBe(false);
    });

    it('reports a partial selection of the selectable rows as indeterminate', () => {
        const { table } = renderSelectable([1, 2]);
        expect(table.allSelected()).toBe(false);
        expect(table.indeterminate()).toBe(true);

        table.toggleAll();
        expect(table.selectedItems().map((row) => row['id'])).toEqual([1, 2, 3]);
    });

    it('does nothing when no row is selectable', () => {
        const fixture = TestBed.createComponent(AppTableComponent);
        fixture.componentRef.setInput('columns', [{ key: 'name', label: 'Name' }]);
        fixture.componentRef.setInput('data', ROWS);
        fixture.componentRef.setInput('selectable', true);
        fixture.componentRef.setInput('rowSelectable', () => false);
        fixture.componentRef.setInput('initialSelectedIds', [1, 2]);
        fixture.detectChanges();

        fixture.componentInstance.toggleAll();

        expect(fixture.componentInstance.selectedItems().map((row) => row['id'])).toEqual([1, 2]);
    });
});

describe('AppTableComponent rowVisible', () => {
    const ROWS = [
        { id: 1, name: 'alpha' },
        { id: 2, name: 'beta' },
        { id: 3, name: 'alpine' },
    ];
    const startsWithAl = (row: TableRow): boolean => (row['name'] as string).startsWith('al');

    function renderFiltered(initialSelectedIds: number[]) {
        const fixture = TestBed.createComponent(AppTableComponent);
        fixture.componentRef.setInput('columns', [{ key: 'name', label: 'Name' }]);
        fixture.componentRef.setInput('data', ROWS);
        fixture.componentRef.setInput('selectable', true);
        fixture.componentRef.setInput('initialSelectedIds', initialSelectedIds);
        fixture.detectChanges();
        const table = fixture.componentInstance;
        const emitted: unknown[][] = [];
        table.selectionChange.subscribe((rows) => emitted.push(rows.map((row) => row['id'])));
        const setRowVisible = (predicate: ((row: TableRow) => boolean) | null): void => {
            fixture.componentRef.setInput('rowVisible', predicate);
            fixture.detectChanges();
        };
        const visibleIds = (): unknown[] => table.filteredData().map((row) => row['id']);
        const renderedRowCount = (): number =>
            (fixture.nativeElement as HTMLElement).querySelectorAll('.table-body .table-row').length;
        const selectedIds = () => table.selectedItems().map((row) => row['id']);
        return { fixture, table, emitted, setRowVisible, visibleIds, renderedRowCount, selectedIds };
    }

    it('hides rejected rows without unticking them', () => {
        const { emitted, setRowVisible, visibleIds, renderedRowCount, selectedIds } = renderFiltered([1, 2]);
        emitted.length = 0;

        setRowVisible(startsWithAl);
        expect(visibleIds()).toEqual([1, 3]);
        expect(renderedRowCount()).toBe(2);
        expect(selectedIds()).toEqual([1, 2]);
        expect(emitted).toEqual([]);

        setRowVisible(null);
        expect(visibleIds()).toEqual([1, 2, 3]);
        expect(renderedRowCount()).toBe(3);
        expect(selectedIds()).toEqual([1, 2]);
    });

    it('selects all visible rows and keeps the hidden selection', () => {
        const { table, emitted, setRowVisible, selectedIds } = renderFiltered([2]);
        setRowVisible(startsWithAl);
        expect(table.allSelected()).toBe(false);

        table.toggleAll();

        expect(selectedIds()).toEqual([1, 2, 3]);
        expect(emitted.at(-1)).toEqual([1, 2, 3]);
        expect(table.allSelected()).toBe(true);
    });

    it('deselects only the visible rows', () => {
        const { table, setRowVisible, selectedIds } = renderFiltered([1, 2, 3]);
        setRowVisible(startsWithAl);

        table.toggleAll();

        expect(selectedIds()).toEqual([2]);
        expect(table.allSelected()).toBe(false);
        expect(table.indeterminate()).toBe(false);
    });

    it('still prunes a selected row that is removed from data', () => {
        const { fixture, emitted, setRowVisible, selectedIds } = renderFiltered([1, 2]);
        setRowVisible(startsWithAl);

        fixture.componentRef.setInput('data', [ROWS[0], ROWS[2]]);
        fixture.detectChanges();

        expect(selectedIds()).toEqual([1]);
        expect(emitted.at(-1)).toEqual([1]);
    });

    it('shows the no-results state, not the empty state, when every row is hidden', () => {
        const { fixture, setRowVisible } = renderFiltered([]);

        setRowVisible(() => false);

        const element = fixture.nativeElement as HTMLElement;
        expect(element.querySelector('.table-no-results')).not.toBeNull();
    });

    it('shows the empty state, not the no-results state, when data is empty', () => {
        const fixture = TestBed.createComponent(EmptyTableHostComponent);
        fixture.detectChanges();

        const element = fixture.nativeElement as HTMLElement;
        expect(element.querySelector('.table-no-results')).toBeNull();
        expect(element.querySelector('.empty-slot')?.textContent).toContain('No rows yet');
    });
});

@Component({
    imports: [AppTableComponent],
    template: `
        <app-table
            [columns]="columns"
            [data]="[]"
            [rowVisible]="hideEveryRow"
        >
            <div
                tableEmpty
                class="empty-slot"
            >
                No rows yet
            </div>
        </app-table>
    `,
})
class EmptyTableHostComponent {
    readonly columns: AppTableColumnDef[] = [{ key: 'name', label: 'Name' }];
    readonly hideEveryRow = (): boolean => false;
}
