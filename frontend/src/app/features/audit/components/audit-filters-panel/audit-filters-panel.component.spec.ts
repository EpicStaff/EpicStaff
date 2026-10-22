import { TestBed } from '@angular/core/testing';
import { ConfirmationDialogService, ConfirmationResult } from '@shared/components';
import { of } from 'rxjs';

import { AuditFilterState, DEFAULT_MATCH_SCOPE, EMPTY_AUDIT_FILTER } from '../../models/audit-filter.models';
import { AuditPresetsStorageService } from '../../services/audit-presets-storage.service';
import { AuditFiltersPanelComponent, AuditFilterTab } from './audit-filters-panel.component';

const matchScope = { ...DEFAULT_MATCH_SCOPE, children: true };

// The template is never rendered: these tests drive the tab switch through the class only.
function setup(filter: AuditFilterState, tab: AuditFilterTab, dialogResult: ConfirmationResult = 'close') {
    const confirm = vi.fn(() => of(dialogResult));
    TestBed.configureTestingModule({
        providers: [{ provide: ConfirmationDialogService, useValue: { confirm } }],
    });
    TestBed.overrideComponent(AuditFiltersPanelComponent, {
        set: { providers: [{ provide: AuditPresetsStorageService, useValue: {} }] },
    });
    const panel = TestBed.createComponent(AuditFiltersPanelComponent).componentInstance;
    panel.filter.set(filter);
    panel.activeTab.set(tab);
    return { panel, confirm };
}

describe('AuditFiltersPanelComponent tab sync', () => {
    it('writes the Builder filters into the query, but never the search text', () => {
        const { panel } = setup(
            { ...EMPTY_AUDIT_FILTER, searchText: 'needle', statuses: ['failed'], query: 'stale' },
            'builder'
        );

        panel.setActiveTab('query');

        expect(panel.filter()).toMatchObject({ mode: 'query', query: 'status in ("failed")', searchText: 'needle' });
        expect(panel.activeTab()).toBe('query');
    });

    it('leaves an empty query when the Builder has only search text', () => {
        const { panel } = setup({ ...EMPTY_AUDIT_FILTER, searchText: 'needle', query: 'stale' }, 'builder');

        panel.setActiveTab('query');

        expect(panel.filter().query).toBe('');
    });

    it('fills the Builder from a query it can show, without asking', () => {
        const { panel, confirm } = setup(
            { ...EMPTY_AUDIT_FILTER, mode: 'query', query: 'STATUS = failed', searchText: 'needle' },
            'query'
        );

        panel.setActiveTab('builder');

        expect(confirm).not.toHaveBeenCalled();
        expect(panel.filter()).toMatchObject({ mode: 'builder', statuses: ['failed'], searchText: 'needle' });
        expect(panel.activeTab()).toBe('builder');
    });

    describe('a query too complex for the Builder', () => {
        const complex: AuditFilterState = {
            ...EMPTY_AUDIT_FILTER,
            mode: 'query',
            query: 'status = failed or kind = event',
            searchText: 'needle',
            matchScope,
        };

        it('keeps the query and the tab on "Keep editing in Query Code"', () => {
            const { panel, confirm } = setup(complex, 'query', false);

            panel.setActiveTab('builder');

            expect(confirm).toHaveBeenCalledOnce();
            expect(panel.filter()).toEqual(complex);
            expect(panel.activeTab()).toBe('query');
        });

        it('clears the query and the Builder, keeping scope and search text, on "Clear and start in Builder"', () => {
            const { panel } = setup({ ...complex, statuses: ['completed'] }, 'query', true);

            panel.setActiveTab('builder');

            expect(panel.filter()).toEqual({ ...EMPTY_AUDIT_FILTER, searchText: 'needle', matchScope });
            expect(panel.activeTab()).toBe('builder');
        });
    });
});
