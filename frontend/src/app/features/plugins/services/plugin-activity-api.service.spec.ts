import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';

import { ApiGetRequest } from '../../../core/models/api-request.model';
import { ConfigService } from '../../../services/config';
import { OrganizationServiceAccount, PluginActivityEvent } from '../models/plugin-activity.model';
import { buildOrganizationServiceAccount, buildPluginActivityEvent } from '../testing/plugin-fixtures';
import { PluginActivityApiService } from './plugin-activity-api.service';

function activityPage(events: PluginActivityEvent[]): ApiGetRequest<PluginActivityEvent> {
    return { count: events.length, next: null, previous: null, results: events };
}

describe('PluginActivityApiService', () => {
    let http: HttpTestingController;
    let api: PluginActivityApiService;

    beforeEach(() => {
        TestBed.configureTestingModule({
            providers: [
                provideHttpClient(),
                provideHttpClientTesting(),
                { provide: ConfigService, useValue: { apiUrl: '/api/' } },
            ],
        });
        http = TestBed.inject(HttpTestingController);
        api = TestBed.inject(PluginActivityApiService);
    });

    afterEach(() => http.verify());

    it("gets a page of the active organization's activity", () => {
        const body = activityPage([buildPluginActivityEvent()]);
        let answer: ApiGetRequest<PluginActivityEvent> | undefined;

        api.listOrganizationActivity({ page: 2, pageSize: 50 }).subscribe((response) => (answer = response));
        const request = http.expectOne((candidate) => candidate.url === '/api/plugins/activity/');
        request.flush(body);

        expect(request.request.method).toBe('GET');
        expect(request.request.params.keys().sort()).toEqual(['page', 'page_size']);
        expect(request.request.params.get('page')).toBe('2');
        expect(request.request.params.get('page_size')).toBe('50');
        expect(answer).toEqual(body);
    });

    it('narrows the organization activity to one plugin and one action', () => {
        api.listOrganizationActivity({ page: 1, pageSize: 50, plugin: 'weather', action: 'api_request' }).subscribe();
        const request = http.expectOne((candidate) => candidate.url === '/api/plugins/activity/');
        request.flush(activityPage([]));

        expect(request.request.params.get('plugin')).toBe('weather');
        expect(request.request.params.get('action')).toBe('api_request');
    });

    it('gets the service accounts acting in the active organization', () => {
        const body = [buildOrganizationServiceAccount()];
        let answer: OrganizationServiceAccount[] | undefined;

        api.listOrganizationServiceAccounts().subscribe((response) => (answer = response));
        const request = http.expectOne('/api/plugins/service-accounts/');
        request.flush(body);

        expect(request.request.method).toBe('GET');
        expect(answer).toEqual(body);
    });

    it("gets a page of one plugin's activity across organizations, optionally of one organization", () => {
        api.listPluginActivity('weather', { page: 1, pageSize: 50 }).subscribe();
        const unfiltered = http.expectOne((candidate) => candidate.url === '/api/admin/plugins/weather/activity/');
        unfiltered.flush(activityPage([]));
        expect(unfiltered.request.params.has('organization_id')).toBe(false);

        api.listPluginActivity('weather', {
            page: 3,
            pageSize: 20,
            organizationId: 7,
            action: 'restarted',
        }).subscribe();
        const filtered = http.expectOne((candidate) => candidate.url === '/api/admin/plugins/weather/activity/');
        filtered.flush(activityPage([]));

        expect(filtered.request.method).toBe('GET');
        expect(filtered.request.params.get('page')).toBe('3');
        expect(filtered.request.params.get('page_size')).toBe('20');
        expect(filtered.request.params.get('organization_id')).toBe('7');
        expect(filtered.request.params.get('action')).toBe('restarted');
    });

    it('keeps the plugin identifier one path segment', () => {
        api.listPluginActivity('../x', { page: 1, pageSize: 50 }).subscribe();

        http.expectOne((candidate) => candidate.url === '/api/admin/plugins/..%2Fx/activity/').flush(activityPage([]));
    });
});
