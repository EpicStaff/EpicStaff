import { TestBed } from '@angular/core/testing';

import { AppTableComponent } from './table.component';
import { AppTableColumnDef } from './table.model';

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
