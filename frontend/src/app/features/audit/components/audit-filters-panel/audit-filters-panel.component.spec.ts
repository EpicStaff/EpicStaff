import { TestBed } from '@angular/core/testing';
import { ConfirmationDialogService, ConfirmationResult } from '@shared/components';
import { of } from 'rxjs';

import { AUDIT_FIELD_CATALOG, AuditFieldCatalog, AuditLookupOptions } from '../../models/audit-domain.models';
import { AuditFilterState, DEFAULT_MATCH_SCOPE, EMPTY_AUDIT_FILTER } from '../../models/audit-filter.models';
import { SESSION_FIELD_CATALOG } from '../../models/audit-filter-options';
import { USER_ACTION_FIELD_CATALOG } from '../../models/audit-user-action-filter-options';
import { AuditPresetsStorageService } from '../../services/audit-presets-storage.service';
import { AuditFiltersPanelComponent, AuditFilterTab } from './audit-filters-panel.component';

const matchScope = { ...DEFAULT_MATCH_SCOPE, children: true };

// The template is never rendered: these tests drive the tab switch through the class only.
function setup(
    filter: AuditFilterState,
    tab: AuditFilterTab,
    dialogResult: ConfirmationResult = 'close',
    catalog: AuditFieldCatalog = SESSION_FIELD_CATALOG
) {
    const confirm = vi.fn(() => of(dialogResult));
    TestBed.configureTestingModule({
        providers: [
            { provide: ConfirmationDialogService, useValue: { confirm } },
            { provide: AUDIT_FIELD_CATALOG, useValue: catalog },
        ],
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

describe('AuditFiltersPanelComponent for user actions', () => {
    function renderPanel(tab: AuditFilterTab, lookupOptions: AuditLookupOptions = {}) {
        TestBed.configureTestingModule({
            providers: [{ provide: AUDIT_FIELD_CATALOG, useValue: USER_ACTION_FIELD_CATALOG }],
        });
        TestBed.overrideComponent(AuditFiltersPanelComponent, {
            set: {
                providers: [
                    {
                        provide: AuditPresetsStorageService,
                        useValue: { load: () => undefined, presetsInScope: () => [] },
                    },
                ],
            },
        });
        const fixture = TestBed.createComponent(AuditFiltersPanelComponent);
        fixture.componentRef.setInput('lookupOptions', lookupOptions);
        fixture.componentInstance.activeTab.set(tab);
        fixture.detectChanges();
        return fixture;
    }

    const render = (tab: AuditFilterTab): HTMLElement => renderPanel(tab).nativeElement;

    const texts = (root: HTMLElement, selector: string) =>
        Array.from(root.querySelectorAll(selector)).map((element) => element.textContent?.trim());

    it('user actions panel offers only user action fields, in Quick and Deep filters', () => {
        const builder = render('builder');

        const sectionsAndGroups = texts(builder, '.filters-panel__section, .filter-group__title');
        expect(sectionsAndGroups).toEqual([
            'Quick filters',
            'Action',
            'User',
            'Target Type',
            'Flow',
            'Date',
            'Deep filters',
            'Target Name',
        ]);
        expect(builder.querySelector('app-audit-match-scope')).toBeNull();
    });

    it('picks target types from the loaded list by their raw value', () => {
        const fixture = renderPanel('builder', {
            targetTypes: [
                { value: 'flow', label: 'Flow' },
                { value: 'python node', label: 'Python node' },
            ],
        });
        const targetType: HTMLElement = Array.from<HTMLElement>(
            fixture.nativeElement.querySelectorAll('app-audit-filter-group')
        ).find((item) => item.querySelector('.filter-group__title')?.textContent?.trim() === 'Target Type')!;

        expect(texts(targetType, '.checkbox-enum__option span')).toEqual(['Flow', 'Python node']);

        targetType.querySelectorAll<HTMLInputElement>('.checkbox-enum__option input')[1].click();
        fixture.detectChanges();

        expect(fixture.componentInstance.filter().selections).toEqual({
            target_type: { op: 'in', values: ['python node'] },
        });
        expect(targetType.querySelector('.filter-group__summary')?.textContent?.trim()).toBe('is any of Python node');
    });

    it('offers the org members and flows by name and picks them by id', () => {
        const fixture = renderPanel('builder', {
            members: [{ value: '3', label: 'Ann Lee (ann@example.com)' }],
            flows: [
                { value: '12', label: 'Billing' },
                { value: '15', label: 'Onboarding' },
            ],
        });
        const groups: HTMLElement[] = Array.from(fixture.nativeElement.querySelectorAll('app-audit-filter-group'));
        const group = (label: string) =>
            groups.find((item) => item.querySelector('.filter-group__title')?.textContent?.trim() === label)!;

        expect(texts(group('User'), '.checkbox-enum__option span')).toEqual(['Ann Lee (ann@example.com)']);
        expect(texts(group('Flow'), '.checkbox-enum__option span')).toEqual(['Billing', 'Onboarding']);

        group('Flow').querySelector<HTMLInputElement>('.checkbox-enum__option input')!.click();
        fixture.detectChanges();

        expect(fixture.componentInstance.filter().selections).toEqual({ flow_id: { op: 'in', values: ['12'] } });
        expect(group('Flow').querySelector('.filter-group__summary')?.textContent?.trim()).toBe('is any of Billing');
    });

    it('lists only user action fields for Query Code', () => {
        const query = render('query');

        expect(texts(query, '.filters-panel__field')).toEqual([
            'action',
            'actor_email',
            'actor_api_key_name',
            'actor_user_id',
            'target_type',
            'target_name',
            'target_id',
            'previous_name',
            'parent_type',
            'parent_name',
            'parent_id',
            'route',
            'event_time',
        ]);
        expect(query.querySelector('app-audit-match-scope')).toBeNull();
    });

    it('writes the user action Builder filters into the query', () => {
        const { panel } = setup(
            { ...EMPTY_AUDIT_FILTER, selections: { action: { op: 'in', values: ['created'] } } },
            'builder',
            'close',
            USER_ACTION_FIELD_CATALOG
        );

        panel.setActiveTab('query');

        expect(panel.filter().query).toBe('action in ("created")');
    });
});
