import { ComponentFixture, TestBed } from '@angular/core/testing';
import { By } from '@angular/platform-browser';
import { provideRouter } from '@angular/router';
import { SelectComponent } from '@shared/components';
import { GetOrganizationResponse } from '@shared/models';
import { Observable, of } from 'rxjs';
import type { Mock } from 'vitest';

import { ApiGetRequest } from '../../../../core/models/api-request.model';
import { AdminOrganizationsService } from '../../../role-base-access/services/admin/organizations.service';
import { PluginAdminActivityComponent } from '../../components/plugin-admin-activity/plugin-admin-activity.component';
import { PluginActivityEvent, PluginAdminActivityQuery } from '../../models/plugin-activity.model';
import { PluginDetail } from '../../models/plugin-admin.model';
import { PluginActivityApiService } from '../../services/plugin-activity-api.service';
import { PluginDialogsService } from '../../services/plugin-dialogs.service';
import { PluginsAdminStorageService } from '../../services/plugins-admin-storage.service';
import { buildPackageReview, buildPluginActivityEvent, buildPluginDetail } from '../../testing/plugin-fixtures';
import { PluginAdminDetailPageComponent } from './plugin-admin-detail-page.component';

class ResizeObserverStub {
    observe(): void {}
    unobserve(): void {}
    disconnect(): void {}
}

function withBackend(hasBackend: boolean): PluginDetail {
    const review = buildPackageReview({ review_state: 'approved' });
    return buildPluginDetail({
        current_package: { ...review, contents: { ...review.contents, has_backend: hasBackend } },
    });
}

function organization(id: number, name: string): GetOrganizationResponse {
    return { id, name } as GetOrganizationResponse;
}

describe('PluginAdminDetailPageComponent tabs', () => {
    let fixture: ComponentFixture<PluginAdminDetailPageComponent>;
    let listPluginActivity: Mock<
        (identifier: string, query: PluginAdminActivityQuery) => Observable<ApiGetRequest<PluginActivityEvent>>
    >;

    function render(plugin: PluginDetail): void {
        TestBed.configureTestingModule({
            imports: [PluginAdminDetailPageComponent],
            providers: [
                provideRouter([]),
                { provide: PluginsAdminStorageService, useValue: { getPlugin: () => of(plugin) } },
                { provide: PluginDialogsService, useValue: {} },
                { provide: PluginActivityApiService, useValue: { listPluginActivity } },
                {
                    provide: AdminOrganizationsService,
                    useValue: {
                        list: () =>
                            of({
                                count: 2,
                                next: null,
                                previous: null,
                                results: [organization(4, 'Bravo'), organization(3, 'Acme')],
                            }),
                    },
                },
            ],
        });
        fixture = TestBed.createComponent(PluginAdminDetailPageComponent);
        fixture.componentRef.setInput('identifier', plugin.identifier);
        refresh();
    }

    function refresh(): void {
        fixture.detectChanges();
        TestBed.tick();
        fixture.detectChanges();
    }

    function tabs(): HTMLElement[] {
        return Array.from((fixture.nativeElement as HTMLElement).querySelectorAll('.detail__tabs app-tab-button'));
    }

    function tabLabels(): string[] {
        return tabs().map((tab) => tab.textContent?.trim() ?? '');
    }

    function openTab(label: string): void {
        tabs()
            .find((tab) => tab.textContent?.trim() === label)!
            .querySelector('button')!
            .click();
        refresh();
    }

    beforeEach(() => {
        vi.stubGlobal('ResizeObserver', ResizeObserverStub);
        listPluginActivity = vi.fn(() =>
            of({ count: 1, next: null, previous: null, results: [buildPluginActivityEvent()] })
        );
    });

    afterEach(() => vi.unstubAllGlobals());

    it('offers Settings, Limits and Runtime for a plugin whose current package has a backend', () => {
        render(withBackend(true));

        expect(tabLabels()).toEqual(['Overview', 'Organizations', 'Settings', 'Limits', 'Runtime', 'Activity']);
    });

    it('offers Overview, Organizations and Activity for a plugin without a backend', () => {
        render(withBackend(false));

        expect(tabLabels()).toEqual(['Overview', 'Organizations', 'Activity']);
    });

    it("shows the plugin's activity in every organization, with an organization column and filter", () => {
        render(withBackend(false));

        openTab('Activity');

        expect(listPluginActivity).toHaveBeenCalledWith('weather', { page: 1, pageSize: 50, organizationId: null });
        const element = fixture.nativeElement as HTMLElement;
        expect(element.querySelector('app-plugin-admin-activity .table-header')?.textContent).toContain('Organization');
        expect(element.querySelector('app-plugin-admin-activity .table-body')?.textContent).toContain(
            'Weather (plugin) on behalf of ada@example.com'
        );

        const filter = fixture.debugElement
            .query(By.directive(PluginAdminActivityComponent))
            .query(By.directive(SelectComponent)).componentInstance as SelectComponent;
        expect(filter.items().map((item) => item.name)).toEqual(['All organizations', 'Acme', 'Bravo']);

        filter.changed.emit(3);
        refresh();

        expect(listPluginActivity).toHaveBeenLastCalledWith('weather', { page: 1, pageSize: 50, organizationId: 3 });
    });
});
