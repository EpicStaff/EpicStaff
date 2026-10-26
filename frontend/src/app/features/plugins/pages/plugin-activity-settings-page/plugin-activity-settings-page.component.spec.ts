import { HttpErrorResponse } from '@angular/common/http';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { By } from '@angular/platform-browser';
import { SelectComponent } from '@shared/components';
import { Observable, of, Subject, throwError } from 'rxjs';
import type { Mock } from 'vitest';

import { ApiGetRequest } from '../../../../core/models/api-request.model';
import {
    OrganizationServiceAccount,
    PluginActivityEvent,
    PluginActivityQuery,
} from '../../models/plugin-activity.model';
import { PluginActivityApiService } from '../../services/plugin-activity-api.service';
import { buildOrganizationServiceAccount, buildPluginActivityEvent } from '../../testing/plugin-fixtures';
import { PluginActivitySettingsPageComponent } from './plugin-activity-settings-page.component';

class ResizeObserverStub {
    observe(): void {}
    unobserve(): void {}
    disconnect(): void {}
}

function activityPage(events: PluginActivityEvent[]): ApiGetRequest<PluginActivityEvent> {
    return { count: events.length, next: null, previous: null, results: events };
}

function forbidden(): Observable<never> {
    return throwError(
        () =>
            new HttpErrorResponse({
                status: 403,
                error: { status_code: 403, code: 'permission_denied', message: 'Forbidden.' },
            })
    );
}

describe('PluginActivitySettingsPageComponent', () => {
    let fixture: ComponentFixture<PluginActivitySettingsPageComponent>;
    let element: HTMLElement;
    let api: {
        listOrganizationServiceAccounts: Mock<() => Observable<OrganizationServiceAccount[]>>;
        listOrganizationActivity: Mock<(query: PluginActivityQuery) => Observable<ApiGetRequest<PluginActivityEvent>>>;
    };

    function render(): void {
        fixture = TestBed.createComponent(PluginActivitySettingsPageComponent);
        element = fixture.nativeElement as HTMLElement;
        refresh();
    }

    function refresh(): void {
        fixture.detectChanges();
        TestBed.tick();
        fixture.detectChanges();
    }

    function text(): string {
        return element.textContent?.replace(/\s+/g, ' ') ?? '';
    }

    beforeEach(() => {
        vi.stubGlobal('ResizeObserver', ResizeObserverStub);
        api = {
            listOrganizationServiceAccounts: vi.fn(() =>
                of([
                    buildOrganizationServiceAccount({ key_last_used_at: new Date(Date.now() - 120_000).toISOString() }),
                    buildOrganizationServiceAccount({
                        plugin: { identifier: 'notes', name: 'Notes', icon_url: '/api/plugin-public/notes/icon/' },
                        grant_state: 'granting',
                        access: [],
                    }),
                ])
            ),
            listOrganizationActivity: vi.fn(() => of(activityPage([buildPluginActivityEvent()]))),
        };
        TestBed.configureTestingModule({
            imports: [PluginActivitySettingsPageComponent],
            providers: [{ provide: PluginActivityApiService, useValue: api }],
        });
    });

    afterEach(() => vi.unstubAllGlobals());

    it('lists the plugins acting in the organization as cards with their state, key use and declared access', () => {
        render();

        const cards = Array.from(element.querySelectorAll('app-plugin-service-account-card'));
        expect(cards.map((card) => card.querySelector('.account__name')?.textContent?.trim())).toEqual([
            'Weather',
            'Notes',
        ]);
        const weather = cards[0].textContent?.replace(/\s+/g, ' ') ?? '';
        expect(weather).toContain('Active');
        expect(weather).toContain('Key last used 2m ago');
        expect(weather).toContain('Creates the Weather forecast flow and runs it for you.');
        expect(weather).toContain('View, Create, Edit, Use');
        const notes = cards[1].textContent?.replace(/\s+/g, ' ') ?? '';
        expect(notes).toContain('Installing');
        expect(notes).toContain('Key last used Never');
        expect(notes).toContain('None. The plugin cannot read or change anything in EpicStaff.');
    });

    it("shows the organization's activity across plugins, without an organization column", () => {
        render();

        expect(api.listOrganizationActivity).toHaveBeenCalledWith({ page: 1, pageSize: 50, plugin: null });
        const header = element.querySelector('app-plugin-activity-list .table-header')?.textContent ?? '';
        expect(header).toContain('Plugin');
        expect(header).not.toContain('Organization');
        expect(element.querySelector('app-plugin-activity-list .table-body')?.textContent).toContain(
            'Weather (plugin) on behalf of ada@example.com'
        );
    });

    it('narrows the activity to the plugin picked from the plugins acting here', () => {
        render();
        const filter = fixture.debugElement.query(By.directive(SelectComponent)).componentInstance as SelectComponent;
        expect(filter.items().map((item) => item.name)).toEqual(['All plugins', 'Weather', 'Notes']);

        // While the narrowed list loads, the old list is gone.
        api.listOrganizationActivity.mockReturnValueOnce(new Subject<ApiGetRequest<PluginActivityEvent>>());
        filter.changed.emit('weather');
        refresh();

        expect(api.listOrganizationActivity).toHaveBeenLastCalledWith({ page: 1, pageSize: 50, plugin: 'weather' });
        expect(element.querySelector('app-plugin-activity-list .table-body')).toBeNull();

        filter.changed.emit(null);
        refresh();

        expect(api.listOrganizationActivity).toHaveBeenLastCalledWith({ page: 1, pageSize: 50, plugin: null });
    });

    it('says so when no plugin acts here and nothing happened yet', () => {
        api.listOrganizationServiceAccounts.mockReturnValue(of([]));
        api.listOrganizationActivity.mockReturnValue(of(activityPage([])));
        render();

        expect(text()).toContain('No plugin with a backend is granted to this organization.');
        expect(text()).toContain('No plugin has done anything in this organization yet.');
    });

    it.each([
        ['the service accounts', 'listOrganizationServiceAccounts' as const],
        ['the activity', 'listOrganizationActivity' as const],
    ])('explains a refusal of %s instead of showing either section', (_case, endpoint) => {
        api[endpoint].mockReturnValue(forbidden());
        render();

        expect(text()).toContain('No access to plugin activity');
        expect(text()).toContain('needs the View permission on Audit');
        expect(element.querySelector('app-plugin-service-account-card')).toBeNull();
        expect(element.querySelector('app-plugin-activity-list')).toBeNull();
    });

    it('shows a failure to load the activity next to the activity, with Retry', () => {
        api.listOrganizationActivity.mockReturnValueOnce(
            throwError(() => new HttpErrorResponse({ status: 500, error: null }))
        );
        render();

        const alert = element.querySelector('[role="alert"]');
        expect(alert?.textContent).toContain("Couldn't load the activity.");
        expect(element.querySelector('app-plugin-service-account-card')).not.toBeNull();

        Array.from(alert!.querySelectorAll('button'))
            .find((button) => button.textContent?.trim() === 'Retry')!
            .click();
        refresh();

        expect(api.listOrganizationActivity).toHaveBeenCalledTimes(2);
        expect(element.querySelector('[role="alert"]')).toBeNull();
    });
});
