import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';

import { ConfigService } from '../../../services/config';
import { PluginGrant } from '../models/plugin-admin.model';
import { PluginSuspendPreview } from '../models/plugin-suspend-preview.model';
import { buildPluginGrant, buildSuspendPreview } from '../testing/plugin-fixtures';
import { PluginsAdminApiService } from './plugins-admin-api.service';

describe('PluginsAdminApiService', () => {
    let http: HttpTestingController;
    let api: PluginsAdminApiService;

    beforeEach(() => {
        TestBed.configureTestingModule({
            providers: [
                provideHttpClient(),
                provideHttpClientTesting(),
                { provide: ConfigService, useValue: { apiUrl: '/api/' } },
            ],
        });
        http = TestBed.inject(HttpTestingController);
        api = TestBed.inject(PluginsAdminApiService);
    });

    afterEach(() => http.verify());

    it('asks to run a failed install hook again and answers with the grant installing', () => {
        const body = buildPluginGrant({ state: 'granting' });
        let answer: PluginGrant | undefined;

        api.retryInstallHook('weather', 5).subscribe((grant) => (answer = grant));
        const request = http.expectOne('/api/admin/plugins/weather/grants/5/retry-hook/');
        request.flush(body, { status: 202, statusText: 'Accepted' });

        expect(request.request.method).toBe('POST');
        expect(answer).toEqual(body);
    });

    it('reads what suspending a grant would stop', () => {
        const body = buildSuspendPreview();
        let answer: PluginSuspendPreview | undefined;

        api.getSuspendPreview('weather', 5).subscribe((preview) => (answer = preview));
        const request = http.expectOne('/api/admin/plugins/weather/grants/5/suspend-preview/');
        request.flush(body);

        expect(request.request.method).toBe('GET');
        expect(answer).toEqual(body);
    });

    it('suspends a grant with an empty body and answers with the grant suspended', () => {
        const body = buildPluginGrant({
            state: 'suspended',
            allowed_actions: ['resume'],
            suspended_at: '2026-10-21T09:00:00Z',
            purge_after: '2026-11-20T09:00:00Z',
        });
        let answer: PluginGrant | undefined;

        api.suspendGrant('weather', 5).subscribe((grant) => (answer = grant));
        const request = http.expectOne('/api/admin/plugins/weather/grants/5/suspend/');
        request.flush(body);

        expect(request.request.method).toBe('POST');
        expect(request.request.body).toBeNull();
        expect(answer).toEqual(body);
    });

    it('resumes a grant with an empty body and answers with the grant as it is now', () => {
        const body = buildPluginGrant();
        let answer: PluginGrant | undefined;

        api.resumeGrant('weather', 5).subscribe((grant) => (answer = grant));
        const request = http.expectOne('/api/admin/plugins/weather/grants/5/resume/');
        request.flush(body);

        expect(request.request.method).toBe('POST');
        expect(request.request.body).toBeNull();
        expect(answer).toEqual(body);
    });

    it('encodes the plugin identifier in grant paths', () => {
        api.suspendGrant('my plugin', 5).subscribe();

        http.expectOne('/api/admin/plugins/my%20plugin/grants/5/suspend/').flush(buildPluginGrant());
    });
});
