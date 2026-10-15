import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { BinnedWebhookTrigger, WebhookTriggerModel } from '@shared/models';

import { ConfigService } from '../../../services/config';
import { WebhookTriggerService } from './webhook-trigger.service';

// A trigger exactly as `GET /webhook-triggers/{id}/` returns it, read-only fields included.
const LOADED_TRIGGER: WebhookTriggerModel = {
    id: 5,
    path: 'orders',
    provider_type: 'localhost',
    ngrok_config: null,
    localhost_config: { name: 'Local orders', domain: null },
    live_url: 'http://localhost:8009/webhooks/orders/',
    auth: { kind: 'webhook', secret_tail: '…a1b2', secret_id: null },
    created_by: { id: 2, display_name: 'Grace Hopper', avatar_url: null },
    created_at: '2026-09-15T08:00:00Z',
    last_edited_by: { id: 3, display_name: 'Ada Lovelace', avatar_url: 'https://example.com/avatars/3.png' },
    last_edited_at: '2026-10-01T09:30:00Z',
};

const READ_ONLY_KEYS = ['id', 'live_url', 'auth', 'created_by', 'created_at', 'last_edited_by', 'last_edited_at'];

describe('WebhookTriggerService payloads', () => {
    let service: WebhookTriggerService;
    let httpMock: HttpTestingController;

    beforeEach(() => {
        TestBed.configureTestingModule({
            providers: [
                provideHttpClient(),
                provideHttpClientTesting(),
                { provide: ConfigService, useValue: { apiUrl: '/api/' } as unknown as ConfigService },
            ],
        });
        service = TestBed.inject(WebhookTriggerService);
        httpMock = TestBed.inject(HttpTestingController);
    });

    afterEach(() => httpMock.verify());

    it('does not send the read-only fields back when a loaded trigger is updated as-is', () => {
        service.update(5, LOADED_TRIGGER).subscribe();

        const request = httpMock.expectOne('/api/webhook-triggers/5/');
        expect(request.request.method).toBe('PATCH');
        expect(request.request.body).toEqual({
            path: 'orders',
            provider_type: 'localhost',
            ngrok_config: null,
            localhost_config: { name: 'Local orders', domain: null },
        });
        for (const key of READ_ONLY_KEYS) {
            expect(request.request.body).not.toHaveProperty(key);
        }
        request.flush(LOADED_TRIGGER);
    });

    it('sends the auth keys only when the caller set them', () => {
        service
            .create({
                path: 'telegram-bot',
                provider_type: 'ngrok',
                ngrok_config: { name: 'Bot tunnel', auth_token_secret_id: 9, domain: null, region: 'eu' },
                localhost_config: null,
                auth_kind: 'telegram',
                auth_secret_id: 12,
            })
            .subscribe();

        const request = httpMock.expectOne('/api/webhook-triggers/');
        expect(request.request.method).toBe('POST');
        expect(request.request.body).toEqual({
            path: 'telegram-bot',
            provider_type: 'ngrok',
            ngrok_config: { name: 'Bot tunnel', auth_token_secret_id: 9, domain: null, region: 'eu' },
            localhost_config: null,
            auth_kind: 'telegram',
            auth_secret_id: 12,
        });
        request.flush({ ...LOADED_TRIGGER, id: 6, path: 'telegram-bot' });
    });

    it('leaves auth_kind out when only the secret changed', () => {
        service.update(5, { ...LOADED_TRIGGER, auth_secret_id: 12 }).subscribe();

        const request = httpMock.expectOne('/api/webhook-triggers/5/');
        expect(request.request.body).toHaveProperty('auth_secret_id', 12);
        expect(request.request.body).not.toHaveProperty('auth_kind');
        request.flush(LOADED_TRIGGER);
    });
});

describe('WebhookTriggerService recycle bin', () => {
    const BIN = '/api/webhook-triggers/recycle-bin/';
    let service: WebhookTriggerService;
    let httpMock: HttpTestingController;

    beforeEach(() => {
        TestBed.configureTestingModule({
            providers: [
                provideHttpClient(),
                provideHttpClientTesting(),
                { provide: ConfigService, useValue: { apiUrl: '/api/' } as unknown as ConfigService },
            ],
        });
        service = TestBed.inject(WebhookTriggerService);
        httpMock = TestBed.inject(HttpTestingController);
    });

    afterEach(() => httpMock.verify());

    function binEntry(id: number) {
        return { id, name: `hook-${id}`, deleted_at: '2026-10-01T10:00:00Z', days_left: 5 };
    }

    it('reads every page of the paged bin and keeps only the id and name', () => {
        let result: BinnedWebhookTrigger[] | undefined;
        service.listInRecycleBin().subscribe((triggers) => (result = triggers));

        const first = Array.from({ length: 100 }, (_, index) => binEntry(index + 1));
        httpMock
            .expectOne(`${BIN}?limit=100&offset=0`)
            .flush({ count: 101, next: null, previous: null, results: first });
        httpMock
            .expectOne(`${BIN}?limit=100&offset=100`)
            .flush({ count: 101, next: null, previous: null, results: [binEntry(101)] });

        expect(result).toHaveLength(101);
        expect(result?.at(-1)).toEqual({ id: 101, name: 'hook-101' });
    });

    it('returns an empty list for an empty bin', () => {
        let result: BinnedWebhookTrigger[] | undefined;
        service.listInRecycleBin().subscribe((triggers) => (result = triggers));

        httpMock.expectOne(`${BIN}?limit=100&offset=0`).flush({ count: 0, next: null, previous: null, results: [] });

        expect(result).toEqual([]);
    });
});
