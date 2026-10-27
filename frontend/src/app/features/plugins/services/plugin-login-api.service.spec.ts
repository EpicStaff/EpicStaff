import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';

import { ConfigService } from '../../../services/config';
import { PluginLoginOrganizations } from '../models/plugin-login.model';
import { PluginLoginApiService } from './plugin-login-api.service';

describe('PluginLoginApiService', () => {
    let http: HttpTestingController;
    let api: PluginLoginApiService;

    beforeEach(() => {
        TestBed.configureTestingModule({
            providers: [
                provideHttpClient(),
                provideHttpClientTesting(),
                { provide: ConfigService, useValue: { apiUrl: '/api/' } },
            ],
        });
        http = TestBed.inject(HttpTestingController);
        api = TestBed.inject(PluginLoginApiService);
    });

    afterEach(() => http.verify());

    it('gets the login organizations of one plugin', () => {
        const body: PluginLoginOrganizations = {
            plugin: { identifier: 'weather', name: 'Weather', icon_url: '/api/plugin-public/weather/icon/?v=0.3.0' },
            organizations: [{ id: 3, name: 'Acme' }],
        };
        let answer: PluginLoginOrganizations | undefined;

        api.loginOrganizations('weather').subscribe((response) => (answer = response));
        const request = http.expectOne('/api/plugins/weather/login-organizations/');
        request.flush(body);

        expect(request.request.method).toBe('GET');
        expect(answer).toEqual(body);
    });

    it('keeps the identifier one path segment', () => {
        api.loginOrganizations('../x').subscribe();

        http.expectOne('/api/plugins/..%2Fx/login-organizations/').flush({});
    });
});
