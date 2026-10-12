import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';

import { SKIP_AUTH_HEADER_OVERRIDE } from '../../../core/interceptors/skip-auth-header-override.context';
import { SKIP_FORBIDDEN_RELOAD } from '../../../core/interceptors/skip-forbidden-reload.context';
import { ConfigService } from '../../../services/config';
import { ChatApiService } from './chat-api.service';

describe('ChatApiService', () => {
    let service: ChatApiService;
    let httpMock: HttpTestingController;

    beforeEach(() => {
        TestBed.configureTestingModule({
            providers: [
                provideHttpClient(),
                provideHttpClientTesting(),
                { provide: ConfigService, useValue: { chatApiUrl: '/chat/' } as unknown as ConfigService },
            ],
        });
        service = TestBed.inject(ChatApiService);
        httpMock = TestBed.inject(HttpTestingController);
    });

    afterEach(() => httpMock.verify());

    it('builds operator URLs from the configured chat base', () => {
        service.getConversations({ section: 'human', binding: 'b-1', cursor: 'opaque-2' }).subscribe();
        const request = httpMock.expectOne((candidate) => candidate.url === '/chat/operator/v1/conversations');
        expect(request.request.params.get('section')).toBe('human');
        expect(request.request.params.has('mode')).toBe(false);
        expect(request.request.params.get('binding')).toBe('b-1');
        expect(request.request.params.get('cursor')).toBe('opaque-2');
        expect(request.request.params.has('page')).toBe(false);
        request.flush({ results: [], next_cursor: null });
    });

    it('omits the binding and cursor parameters when neither is set', () => {
        service.getConversations({ section: 'bot', binding: null }).subscribe();
        const request = httpMock.expectOne((candidate) => candidate.url === '/chat/operator/v1/conversations');
        expect(request.request.params.get('section')).toBe('bot');
        expect(request.request.params.has('mode')).toBe(false);
        expect(request.request.params.has('binding')).toBe(false);
        expect(request.request.params.has('cursor')).toBe(false);
        request.flush({ results: [], next_cursor: null });
    });

    it('sends the mode filter with the human section only when it is set', () => {
        service.getConversations({ section: 'human', mode: 'awaiting_human', binding: null }).subscribe();
        const request = httpMock.expectOne((candidate) => candidate.url === '/chat/operator/v1/conversations');
        expect(request.request.params.get('section')).toBe('human');
        expect(request.request.params.get('mode')).toBe('awaiting_human');
        request.flush({ results: [], next_cursor: null });
    });

    it('reads the budget defaults and caps from bindings/limits', () => {
        const limits = {
            defaults: { token_budget_per_conversation: 50000, daily_token_budget: 1000000 },
            caps: { token_budget_per_conversation: 200000, daily_token_budget: 5000000 },
        };
        let received: unknown = null;
        service.getBindingLimits().subscribe((value) => (received = value));
        const request = httpMock.expectOne('/chat/operator/v1/bindings/limits');
        expect(request.request.method).toBe('GET');
        request.flush(limits);
        expect(received).toEqual(limits);
    });

    it('sends only the visitor message extras that are set', () => {
        service.sendAsVisitor('c-1', 'vt', 'hello').subscribe();
        expect(httpMock.expectOne('/chat/public/v1/conversations/c-1/messages').request.body).toEqual({
            content: 'hello',
        });
        service
            .sendAsVisitor('c-1', 'vt', 'Yes', {
                action: { type: 'button', id: 'yes' },
                chat_extra_data: { plan: 'pro' },
            })
            .subscribe();
        expect(httpMock.expectOne('/chat/public/v1/conversations/c-1/messages').request.body).toEqual({
            content: 'Yes',
            action: { type: 'button', id: 'yes' },
            chat_extra_data: { plan: 'pro' },
        });
    });

    it('sends public widget calls with the visitor token and skips the auth and forbidden interceptors', () => {
        service.sendAsVisitor('c-1', 'visitor-token', 'hello').subscribe();
        const request = httpMock.expectOne('/chat/public/v1/conversations/c-1/messages');
        expect(request.request.method).toBe('POST');
        expect(request.request.headers.get('Authorization')).toBe('Bearer visitor-token');
        expect(request.request.context.get(SKIP_AUTH_HEADER_OVERRIDE)).toBe(true);
        expect(request.request.context.get(SKIP_FORBIDDEN_RELOAD)).toBe(true);
        expect(request.request.body).toEqual({ content: 'hello' });
        request.flush({ message_id: 'm-1', state: 'processing' }, { status: 202, statusText: 'Accepted' });
    });

    it('sends a binding patch exactly as given, so unset fields stay unset on the server', () => {
        service.updateBinding('b-1', { daily_token_budget: 20000 }).subscribe();
        const request = httpMock.expectOne('/chat/operator/v1/bindings/b-1');
        expect(request.request.method).toBe('PATCH');
        expect(request.request.body).toEqual({ daily_token_budget: 20000 });
        request.flush({});
    });

    it('checks a flow against the chat contract by graph id', () => {
        let received: unknown = null;
        service.checkContract(7).subscribe((value) => (received = value));
        const request = httpMock.expectOne((candidate) => candidate.url === '/chat/operator/v1/bindings/contract');
        expect(request.request.method).toBe('GET');
        expect(request.request.params.get('graph_id')).toBe('7');
        request.flush({ contract_errors: ['end node lacks reply'] });
        expect(received).toEqual({ contract_errors: ['end node lacks reply'] });
    });

    it('pauses and resumes a binding with an empty POST', () => {
        service.pauseBinding('b-1').subscribe();
        const pause = httpMock.expectOne('/chat/operator/v1/bindings/b-1/pause');
        expect(pause.request.method).toBe('POST');
        expect(pause.request.body).toEqual({});
        pause.flush({});

        service.resumeBinding('b-1').subscribe();
        const resume = httpMock.expectOne('/chat/operator/v1/bindings/b-1/resume');
        expect(resume.request.method).toBe('POST');
        expect(resume.request.body).toEqual({});
        resume.flush({});
    });

    it('issues a visitor token for a test conversation with an empty POST', () => {
        let received: unknown = null;
        service.issueVisitorToken('c-1').subscribe((value) => (received = value));
        const request = httpMock.expectOne('/chat/operator/v1/conversations/c-1/visitor-token');
        expect(request.request.method).toBe('POST');
        expect(request.request.body).toEqual({});
        request.flush({ visitor_token: 'vt-1' }, { status: 201, statusText: 'Created' });
        expect(received).toEqual({ visitor_token: 'vt-1' });
    });

    it('posts the force flag on a claim only when asked', () => {
        service.claim('c-1').subscribe();
        expect(httpMock.expectOne('/chat/operator/v1/conversations/c-1/claim').request.body).toEqual({ force: false });
        service.claim('c-1', true).subscribe();
        expect(httpMock.expectOne('/chat/operator/v1/conversations/c-1/claim').request.body).toEqual({ force: true });
    });
});
