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
