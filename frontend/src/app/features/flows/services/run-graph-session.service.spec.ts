import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';

import { ConfigService } from '../../../services/config';
import { RunGraphResponse, RunTestSessionRequest } from '../models/run-session.model';
import { RunGraphService } from './run-graph-session.service';

describe('RunGraphService', () => {
    let service: RunGraphService;
    let httpMock: HttpTestingController;

    beforeEach(() => {
        TestBed.configureTestingModule({
            providers: [
                provideHttpClient(),
                provideHttpClientTesting(),
                { provide: ConfigService, useValue: { apiUrl: '/api/' } as unknown as ConfigService },
            ],
        });
        service = TestBed.inject(RunGraphService);
        httpMock = TestBed.inject(HttpTestingController);
    });

    afterEach(() => httpMock.verify());

    it('posts the test run request as a JSON body and returns the new session id', () => {
        const testRunRequest: RunTestSessionRequest = {
            graph_id: 3,
            node_type: 'webhook-trigger',
            node_id: 11,
            payload: { order: { id: 42 } },
        };
        let result: RunGraphResponse | undefined;
        service.runTestSession(testRunRequest).subscribe((response) => (result = response));

        const request = httpMock.expectOne('/api/run-session/test/');
        expect(request.request.method).toBe('POST');
        expect(request.request.body).not.toBeInstanceOf(FormData);
        expect(request.request.body).toEqual(testRunRequest);
        request.flush({ session_id: 99 }, { status: 201, statusText: 'Created' });

        expect(result).toEqual({ session_id: 99 });
    });

    it('surfaces the backend error envelope for an invalid payload', () => {
        let errorBody: unknown;
        service
            .runTestSession({ graph_id: 3, node_type: 'telegram-trigger', node_id: 5, payload: {} })
            .subscribe({ error: (error: { error: unknown }) => (errorBody = error.error) });

        const errorEnvelope = {
            status_code: 400,
            code: 'test_run_payload_invalid',
            message: 'Test payload is not a valid Telegram update.',
            errors: ['update_id: Field required'],
        };
        httpMock.expectOne('/api/run-session/test/').flush(errorEnvelope, { status: 400, statusText: 'Bad Request' });

        expect(errorBody).toEqual(errorEnvelope);
    });
});
