import { HttpErrorResponse } from '@angular/common/http';
import { TestBed } from '@angular/core/testing';
import { APP_STORAGE } from '@shared/services';
import { Subject } from 'rxjs';

import { ActiveOrgService } from '../../../services/auth/active-org.service';
import { ToastService } from '../../../services/notifications';
import { provideChatStorages } from '../chat.providers';
import { CHAT_BINDING_DEFAULTS, ChatBinding, ChatMyAlias } from '../models/chat.model';
import { ChatApiService } from './chat-api.service';
import { ChatMyAliasesStorageService } from './chat-my-aliases-storage.service';

const desk = (id: string, operatorName = 'Support'): ChatBinding => ({
    ...CHAT_BINDING_DEFAULTS,
    response_time_seconds: 600,
    on_response_timeout: 'handback',
    handback_message: 'Back to the bot.',
    close_after_seconds: 86_400,
    id,
    org_id: 1,
    graph_id: 5,
    name: id,
    bot_display_name: 'Bot',
    operator_display_name: operatorName,
    public_key: 'pk',
    is_active: true,
    token_budget_per_conversation: 1000,
    daily_token_budget: 1_000_000,
    broken_reason: null,
    contract_errors: [],
    created_at: '',
    updated_at: '',
});

describe('ChatMyAliasesStorageService', () => {
    let storage: ChatMyAliasesStorageService;
    let responses: Subject<ChatMyAlias[]>[];
    const chatApi = {
        getMyAliases: vi.fn(() => {
            const response = new Subject<ChatMyAlias[]>();
            responses.push(response);
            return response;
        }),
    };

    const saved = (bindingId: string, alias: string | null) => ({
        binding_id: bindingId,
        alias,
        visible_name: alias ?? 'Support',
    });

    beforeEach(() => {
        vi.clearAllMocks();
        responses = [];
        TestBed.configureTestingModule({
            providers: [
                provideChatStorages(),
                { provide: ChatApiService, useValue: chatApi },
                { provide: ToastService, useValue: { error: vi.fn() } },
            ],
        });
        TestBed.inject(ActiveOrgService).set(1);
        storage = TestBed.inject(ChatMyAliasesStorageService);
    });

    afterEach(() => localStorage.clear());

    it('loads my aliases by desk; a desk without one uses its operator display name', () => {
        storage.reload();
        responses[0].next([{ binding_id: 'b-1', alias: 'Mike' }]);

        expect(storage.aliasFor('b-1')).toBe('Mike');
        expect(storage.aliasFor('b-2')).toBeNull();
        expect(storage.visibleNameOn(desk('b-1'))).toBe('Mike');
        expect(storage.visibleNameOn(desk('b-2', 'Help team'))).toBe('Help team');
    });

    it('knows no name before a load succeeds: not while the first is in flight, nor after it failed', () => {
        storage.reload();
        expect(storage.isKnown('b-1')).toBe(false);
        expect(storage.visibleNameOn(desk('b-1'))).toBeNull();

        responses[0].error(new HttpErrorResponse({ status: 500 }));
        expect(storage.visibleNameOn(desk('b-1'))).toBeNull();

        storage.reload();
        responses[1].next([]);
        expect(storage.isKnown('b-1')).toBe(true);
        expect(storage.visibleNameOn(desk('b-1'))).toBe('Support');
    });

    it("knows a desk's name once a save answered for it, before any load, and that desk only", () => {
        storage.remember(saved('b-1', 'Mike'));
        expect(storage.visibleNameOn(desk('b-1'))).toBe('Mike');
        expect(storage.visibleNameOn(desk('b-2'))).toBeNull();

        storage.remember(saved('b-2', null));
        expect(storage.visibleNameOn(desk('b-2'))).toBe('Support');
    });

    it('lets only the latest request land', () => {
        storage.reload();
        storage.reload();
        responses[1].next([{ binding_id: 'b-1', alias: 'New' }]);
        responses[0].next([{ binding_id: 'b-1', alias: 'Old' }]);
        expect(storage.aliasFor('b-1')).toBe('New');
    });

    it('shows a save at once, and keeps it over a load that was already in flight', () => {
        storage.reload();
        responses[0].next([{ binding_id: 'b-1', alias: 'Mike' }]);

        storage.reload();
        storage.remember(saved('b-1', null));
        storage.remember(saved('b-2', 'Ann'));
        expect(storage.aliasFor('b-1')).toBeNull();
        expect(storage.aliasFor('b-2')).toBe('Ann');

        // Answered before the saves landed on the server.
        responses[1].next([
            { binding_id: 'b-1', alias: 'Mike' },
            { binding_id: 'b-3', alias: 'Max' },
        ]);
        expect(storage.aliasFor('b-1')).toBeNull();
        expect(storage.aliasFor('b-2')).toBe('Ann');
        expect(storage.aliasFor('b-3')).toBe('Max');

        // A later load is the server's word again.
        storage.reload();
        responses[2].next([{ binding_id: 'b-1', alias: 'Mike' }]);
        expect(storage.aliasFor('b-1')).toBe('Mike');
        expect(storage.aliasFor('b-2')).toBeNull();
    });

    it('keeps the names it has when a load fails', () => {
        storage.reload();
        responses[0].next([{ binding_id: 'b-1', alias: 'Mike' }]);
        storage.reload();
        responses[1].error(new HttpErrorResponse({ status: 500 }));
        expect(storage.aliasFor('b-1')).toBe('Mike');
    });

    it('sends no request without an active org', () => {
        TestBed.inject(ActiveOrgService).set(null);
        storage.reload();
        expect(chatApi.getMyAliases).not.toHaveBeenCalled();
    });

    it("is cleared on org switch and logout: the old org's names go, and a load in flight never lands", () => {
        expect(TestBed.inject(APP_STORAGE)).toContain(storage);
        storage.reload();
        responses[0].next([{ binding_id: 'b-1', alias: 'Mike' }]);
        storage.reload();

        storage.remember(saved('b-2', 'Ann'));
        storage.clear();
        responses[1].next([{ binding_id: 'b-1', alias: 'Mike' }]);
        expect(storage.aliases().size).toBe(0);
        expect(storage.aliasFor('b-1')).toBeNull();
        // Nothing is known for the next org until its own load, or a save there, answers.
        expect(storage.visibleNameOn(desk('b-1'))).toBeNull();
        expect(storage.visibleNameOn(desk('b-2'))).toBeNull();
    });
});
