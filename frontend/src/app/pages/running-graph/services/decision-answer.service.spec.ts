import { HttpErrorResponse, provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';

import { ConfigService } from '../../../services/config/config.service';
import { DecisionAnswerRequest, DecisionAnswerService } from './decision-answer.service';

describe('DecisionAnswerService', () => {
    let service: DecisionAnswerService;
    let httpMock: HttpTestingController;

    const apiUrl = 'http://test-api/';

    beforeEach(() => {
        TestBed.configureTestingModule({
            providers: [
                provideHttpClient(),
                provideHttpClientTesting(),
                { provide: ConfigService, useValue: { apiUrl } },
            ],
        });

        service = TestBed.inject(DecisionAnswerService);
        httpMock = TestBed.inject(HttpTestingController);
    });

    afterEach(() => {
        httpMock.verify();
    });

    it('sends a POST request to the correct URL with the exact payload', () => {
        const sessionId = 'session-123';
        const payload: DecisionAnswerRequest = {
            decision_id: 'decision-abc',
            option_index: 1,
            free_text: null,
        };

        service.submitDecisionAnswer(sessionId, payload).subscribe();

        const req = httpMock.expectOne(`${apiUrl}sessions/${sessionId}/decisions/answer/`);
        expect(req.request.method).toBe('POST');
        expect(req.request.body).toEqual(payload);

        req.flush({});
    });

    it('propagates a 409 Conflict error to the subscriber', () => {
        const sessionId = 'session-123';
        const payload: DecisionAnswerRequest = {
            decision_id: 'decision-abc',
            option_index: 0,
            free_text: null,
        };

        let receivedError: HttpErrorResponse | undefined;

        service.submitDecisionAnswer(sessionId, payload).subscribe({
            next: () => fail('expected an error, not a success response'),
            error: (error: HttpErrorResponse) => (receivedError = error),
        });

        const req = httpMock.expectOne(`${apiUrl}sessions/${sessionId}/decisions/answer/`);
        req.flush({ detail: 'Decision already answered.' }, { status: 409, statusText: 'Conflict' });

        expect(receivedError).toBeDefined();
        expect(receivedError!.status).toBe(409);
    });

    it('propagates a 404 Not Found error to the subscriber', () => {
        const sessionId = 'session-123';
        const payload: DecisionAnswerRequest = {
            decision_id: 'decision-abc',
            option_index: 0,
            free_text: null,
        };

        let receivedError: HttpErrorResponse | undefined;

        service.submitDecisionAnswer(sessionId, payload).subscribe({
            next: () => fail('expected an error, not a success response'),
            error: (error: HttpErrorResponse) => (receivedError = error),
        });

        const req = httpMock.expectOne(`${apiUrl}sessions/${sessionId}/decisions/answer/`);
        req.flush({ detail: 'Not found.' }, { status: 404, statusText: 'Not Found' });

        expect(receivedError).toBeDefined();
        expect(receivedError!.status).toBe(404);
    });
});
