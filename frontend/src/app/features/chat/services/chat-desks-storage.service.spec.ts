import { HttpErrorResponse } from '@angular/common/http';
import { TestBed } from '@angular/core/testing';
import { APP_STORAGE } from '@shared/services';
import { Subject } from 'rxjs';

import { ActiveOrgService } from '../../../services/auth/active-org.service';
import { ToastService } from '../../../services/notifications';
import { provideChatStorages } from '../chat.providers';
import { CHAT_BINDING_DEFAULTS, ChatBinding } from '../models/chat.model';
import { ChatApiService } from './chat-api.service';
import { ChatDesksStorageService } from './chat-desks-storage.service';

const desk = (id: string, name: string): ChatBinding => ({
    ...CHAT_BINDING_DEFAULTS,
    response_time_seconds: 600,
    on_response_timeout: 'handback',
    handback_message: 'Back to the bot.',
    close_after_seconds: 86_400,
    id,
    org_id: 1,
    graph_id: 5,
    name,
    bot_display_name: name,
    public_key: 'pk',
    is_active: true,
    token_budget_per_conversation: 1000,
    daily_token_budget: 1_000_000,
    broken_reason: null,
    contract_errors: [],
    created_at: '',
    updated_at: '',
});

describe('ChatDesksStorageService', () => {
    let storage: ChatDesksStorageService;
    let responses: Subject<ChatBinding[]>[];
    const chatApi = {
        getBindings: vi.fn(() => {
            const response = new Subject<ChatBinding[]>();
            responses.push(response);
            return response;
        }),
    };
    const toast = { error: vi.fn() };

    const failure = (): HttpErrorResponse => new HttpErrorResponse({ status: 500, statusText: 'Server Error' });

    beforeEach(() => {
        vi.clearAllMocks();
        responses = [];
        TestBed.configureTestingModule({
            providers: [
                provideChatStorages(),
                { provide: ChatApiService, useValue: chatApi },
                { provide: ToastService, useValue: toast },
            ],
        });
        TestBed.inject(ActiveOrgService).set(1);
        storage = TestBed.inject(ChatDesksStorageService);
    });

    afterEach(() => localStorage.clear());

    it('loads the desks and tells which request the list it holds came from', () => {
        expect(storage.isLoaded()).toBe(false);
        const request = storage.reload();
        expect(storage.isLoading()).toBe(true);

        responses[0].next([desk('b-1', 'Support')]);
        expect(storage.desks().map(({ id }) => id)).toEqual(['b-1']);
        expect(storage.landedRequest()).toBe(request);
        expect(storage.isLoaded()).toBe(true);
        expect(storage.isLoading()).toBe(false);
    });

    it('lets only the latest request land when two answer out of order', () => {
        storage.reload();
        const latest = storage.reload();
        responses[1].next([desk('b-1', 'Support'), desk('b-2', 'Sales')]);
        responses[0].next([desk('b-1', 'Support')]);
        expect(storage.desks().map(({ id }) => id)).toEqual(['b-1', 'b-2']);
        expect(storage.landedRequest()).toBe(latest);
    });

    it('marks a failed first load without a toast, and clears the mark when it retries', () => {
        storage.reload();
        responses[0].error(failure());
        expect(storage.loadFailed()).toBe(true);
        expect(storage.isLoading()).toBe(false);
        expect(toast.error).not.toHaveBeenCalled();

        storage.reload();
        expect(storage.loadFailed()).toBe(false);
        expect(storage.isLoading()).toBe(true);
    });

    it('keeps the desks shown when a later reload fails, and says so', () => {
        storage.reload();
        responses[0].next([desk('b-1', 'Support')]);
        storage.reload();
        responses[1].error(failure());
        expect(storage.desks().map(({ id }) => id)).toEqual(['b-1']);
        expect(storage.loadFailed()).toBe(false);
        expect(toast.error).toHaveBeenCalledTimes(1);
    });

    it('sends no request without an active org, and a cleared storage stays cleared', () => {
        storage.reload();
        responses[0].next([desk('b-1', 'Support')]);
        // A logout: the storages are cleared and the org is gone before the logout request returns.
        storage.clear();
        TestBed.inject(ActiveOrgService).set(null);

        expect(storage.reload()).toBeNull();
        expect(chatApi.getBindings).toHaveBeenCalledTimes(1);
        expect(storage.desks()).toEqual([]);
        expect(storage.isLoaded()).toBe(false);
        expect(storage.isLoading()).toBe(false);
        expect(storage.loadFailed()).toBe(false);
    });

    it("is cleared on org switch and logout: the old org's desks go, and a request in flight never lands", () => {
        expect(TestBed.inject(APP_STORAGE)).toContain(storage);
        const before = storage.reload();
        responses[0].next([desk('b-1', 'Support')]);
        storage.reload();

        storage.clear();
        responses[1].next([desk('b-1', 'Support')]);
        expect(storage.desks()).toEqual([]);
        expect(storage.isLoaded()).toBe(false);
        expect(storage.landedRequest()).toBe(0);
        expect(storage.isLoading()).toBe(false);
        // Request numbers keep growing, so one taken before the clear never matches a list loaded after it.
        expect(storage.reload()).toBeGreaterThan(before! + 1);
    });
});
