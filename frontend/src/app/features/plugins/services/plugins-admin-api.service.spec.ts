import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';

import { ConfigService } from '../../../services/config';
import { PluginGrant } from '../models/plugin-admin.model';
import { buildPluginGrant } from '../testing/plugin-fixtures';
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
});
