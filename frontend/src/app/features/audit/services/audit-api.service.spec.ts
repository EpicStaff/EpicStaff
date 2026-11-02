import { provideHttpClient } from '@angular/common/http';
import { HttpResponse } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { of, TimeoutError } from 'rxjs';

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

    it('lists the recorded values of a field with the audit token', () => {
        let values: string[] = [];
        service.getFieldValues('user_actions', 'target_type').subscribe((response) => (values = response.values));

        const request = http.expectOne('/auditor/api/audit/user_actions/values/target_type');
        expect(request.request.method).toBe('GET');
        expect(request.request.headers.get('Authorization')).toBe('Bearer audit-token');
        request.flush({ field: 'target_type', values: ['agent', 'python node'] });

        expect(values).toEqual(['agent', 'python node']);
    });

    it('polls the export file under the domain it was started in', () => {
        service.getExportFile('user_actions', 'job 1').subscribe();

        http.expectOne('/auditor/api/audit/user_actions/export/job%201');
    });

    describe('downloadExport', () => {
        const EXPORT_URL = '/auditor/api/audit/sessions/export';
        const FILE_URL = '/auditor/api/audit/sessions/export/job%201';

        beforeEach(() => vi.useFakeTimers());
        afterEach(() => vi.useRealTimers());

        it('starts the job, polls once a second while it answers 202, and emits the 200 file', () => {
            const responses: HttpResponse<Blob>[] = [];
            const file = new Blob(['{}']);
            service.downloadExport('sessions', { format: 'json' }).subscribe((response) => responses.push(response));

            http.expectOne({ method: 'POST', url: EXPORT_URL }).flush({ job_id: 'job 1' });
            vi.advanceTimersByTime(0);
            http.expectOne(FILE_URL).flush(new Blob(), { status: 202, statusText: 'Accepted' });
            vi.advanceTimersByTime(999);
            http.expectNone(FILE_URL);
            vi.advanceTimersByTime(1);
            http.expectOne(FILE_URL).flush(file);
            vi.advanceTimersByTime(5_000);

            expect(responses.map((response) => response.body)).toEqual([file]);
            http.expectNone(FILE_URL);
        });

        it('fails with a timeout when the file is not ready within five minutes', () => {
            let failure: unknown = null;
            service.downloadExport('sessions', { format: 'csv' }).subscribe({ error: (error) => (failure = error) });

            http.expectOne({ method: 'POST', url: EXPORT_URL }).flush({ job_id: 'job 1' });
            vi.advanceTimersByTime(0);
            const pendingPoll = http.expectOne(FILE_URL);
            vi.advanceTimersByTime(5 * 60_000 - 1);
            expect(failure).toBeNull();
            vi.advanceTimersByTime(1);

            expect(failure).toBeInstanceOf(TimeoutError);
            expect(pendingPoll.cancelled).toBe(true);
        });
    });
});
