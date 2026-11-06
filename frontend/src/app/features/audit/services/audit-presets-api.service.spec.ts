import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';

import { ConfigService } from '../../../services/config';
import { AuditPresetsApiService } from './audit-presets-api.service';

describe('AuditPresetsApiService', () => {
    let service: AuditPresetsApiService;
    let http: HttpTestingController;

    beforeEach(() => {
        TestBed.configureTestingModule({
            providers: [
                provideHttpClient(),
                provideHttpClientTesting(),
                { provide: ConfigService, useValue: { apiUrl: '/api/' } },
            ],
        });
        service = TestBed.inject(AuditPresetsApiService);
        http = TestBed.inject(HttpTestingController);
    });

    it('presets api sends domain query param', () => {
        service.getPresets('user_actions').subscribe();

        const request = http.expectOne((req) => req.url === '/api/audit-filter-presets/');
        expect(request.request.params.get('domain')).toBe('user_actions');
        expect(request.request.params.get('limit')).toBe('1000');
    });

    it('sends the domain on writes too', () => {
        service.deletePreset('sessions', 7).subscribe();

        const request = http.expectOne((req) => req.url === '/api/audit-filter-presets/7/');
        expect(request.request.method).toBe('DELETE');
        expect(request.request.params.get('domain')).toBe('sessions');
    });
});
