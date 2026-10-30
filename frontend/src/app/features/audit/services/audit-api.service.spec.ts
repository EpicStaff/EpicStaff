import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { of } from 'rxjs';

import { ConfigService } from '../../../services/config';
import { AuditApiService } from './audit-api.service';
import { AuditTokenService } from './audit-token.service';

describe('AuditApiService', () => {
    let service: AuditApiService;
    let http: HttpTestingController;

    beforeEach(() => {
        TestBed.configureTestingModule({
            providers: [
                provideHttpClient(),
                provideHttpClientTesting(),
                { provide: ConfigService, useValue: { auditorUrl: '/auditor/' } },
                { provide: AuditTokenService, useValue: { getToken: () => of('audit-token') } },
            ],
        });
        service = TestBed.inject(AuditApiService);
        http = TestBed.inject(HttpTestingController);
    });

    it('search posts to api/audit/user_actions/search for user_actions', () => {
        service.search('user_actions', { size: 20 }).subscribe();

        const request = http.expectOne('/auditor/api/audit/user_actions/search');
        expect(request.request.method).toBe('POST');
        expect(request.request.body).toEqual({ size: 20 });
        expect(request.request.headers.get('Authorization')).toBe('Bearer audit-token');
    });

    it('search posts to api/audit/sessions/search for sessions', () => {
        service.search('sessions', {}).subscribe();

        http.expectOne('/auditor/api/audit/sessions/search');
    });

    it('polls the export file under the domain it was started in', () => {
        service.getExportFile('user_actions', 'job 1').subscribe();

        http.expectOne('/auditor/api/audit/user_actions/export/job%201');
    });
});
