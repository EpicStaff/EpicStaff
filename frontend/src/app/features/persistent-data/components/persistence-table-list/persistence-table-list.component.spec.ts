import { TestBed } from '@angular/core/testing';

import { PersistenceTable } from '../../models/persistence-table.model';
import { PersistenceTableListComponent } from './persistence-table-list.component';

const TABLE: PersistenceTable = {
    id: 1,
    name: 'profiles',
    description: '',
    entry_count: 3,
    created_at: '2026-09-24T00:00:00Z',
    updated_at: '2026-09-24T00:00:00Z',
};

function renderList(canRename: boolean, canDelete: boolean): HTMLElement {
    const fixture = TestBed.createComponent(PersistenceTableListComponent);
    fixture.componentRef.setInput('tables', [TABLE]);
    fixture.componentRef.setInput('canRename', canRename);
    fixture.componentRef.setInput('canDelete', canDelete);
    fixture.detectChanges();
    return fixture.nativeElement as HTMLElement;
}

describe('PersistenceTableListComponent permission gating', () => {
    it('shows rename but not delete with update permission only', () => {
        const element = renderList(true, false);
        expect(element.querySelector('[aria-label="Rename table"]')).not.toBeNull();
        expect(element.querySelector('[aria-label="Delete table"]')).toBeNull();
    });

    it('shows delete but not rename with delete permission only', () => {
        const element = renderList(false, true);
        expect(element.querySelector('[aria-label="Rename table"]')).toBeNull();
        expect(element.querySelector('[aria-label="Delete table"]')).not.toBeNull();
    });
});
