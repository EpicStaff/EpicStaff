import { HttpErrorResponse } from '@angular/common/http';
import { TestBed } from '@angular/core/testing';
import { ConfirmationDialogService } from '@shared/components';
import { of, Subject, throwError } from 'rxjs';

import { ToastService } from '../../../services/notifications';
import { ChatConversation } from '../models/chat.model';
import { ChatApiService } from './chat-api.service';
import { ChatConversationActionsService } from './chat-conversation-actions.service';

const conversation = (overrides: Partial<ChatConversation> = {}): ChatConversation => ({
    id: 'c-1',
    binding_id: 'b-1',
    mode: 'awaiting_human',
    state: 'idle',
    is_test: false,
    assigned_operator_id: null,
    tokens_used: 0,
    turns: 0,
    tokens_today: 0,
    turns_today: 0,
    last_message_at: '2026-10-10T10:00:00Z',
    last_message_preview: 'hello',
    handoff_reason: '',
    handoff_at: '2026-10-10T10:00:00Z',
    visitor_number: 1,
    chat_user_id: null,
    assigned_operator_name: null,
    last_message_role: 'user',
    last_message_author_user_id: null,
    last_message_author_name: null,
    visitor_waiting_since: '2026-10-10T10:00:00Z',
    ...overrides,
});

const heldByOther = (): HttpErrorResponse =>
    new HttpErrorResponse({ status: 409, error: { code: 'claimed_by_other', message: 'held' } });

describe('ChatConversationActionsService', () => {
    let service: ChatConversationActionsService;
    let changed: ChatConversation[];
    const chatApi = { claim: vi.fn(), release: vi.fn() };
    const confirmation = { confirm: vi.fn() };
    const toast = { error: vi.fn() };

    beforeEach(() => {
        vi.clearAllMocks();
        TestBed.configureTestingModule({
            providers: [
                { provide: ChatApiService, useValue: chatApi },
                { provide: ConfirmationDialogService, useValue: confirmation },
                { provide: ToastService, useValue: toast },
            ],
        });
        service = TestBed.inject(ChatConversationActionsService);
        changed = [];
        service.changed$.subscribe((row) => changed.push(row));
    });

    it('takes a conversation over and publishes the row the server returned', () => {
        const taken = conversation({ mode: 'human', assigned_operator_id: 3 });
        chatApi.claim.mockReturnValueOnce(of(taken));
        service.takeOver(conversation());
        expect(chatApi.claim).toHaveBeenCalledWith('c-1');
        expect(confirmation.confirm).not.toHaveBeenCalled();
        expect(changed).toEqual([taken]);
        expect(service.isPending()).toBe(false);
    });

    it('asks before taking a conversation another operator holds, then takes it with force', () => {
        const taken = conversation({ mode: 'human', assigned_operator_id: 3 });
        chatApi.claim.mockReturnValueOnce(throwError(heldByOther)).mockReturnValueOnce(of(taken));
        confirmation.confirm.mockReturnValueOnce(of(true));
        service.takeOver(conversation({ mode: 'human', assigned_operator_id: 7 }));
        expect(confirmation.confirm).toHaveBeenCalledWith(
            expect.objectContaining({ title: 'Take over conversation', confirmText: 'Take over', type: 'danger' })
        );
        expect(chatApi.claim).toHaveBeenLastCalledWith('c-1', true);
        expect(changed).toEqual([taken]);
        expect(toast.error).not.toHaveBeenCalled();
    });

    it('takes nothing when the operator cancels the confirm, and is free for the next action', () => {
        chatApi.claim.mockReturnValueOnce(throwError(heldByOther));
        confirmation.confirm.mockReturnValueOnce(of(false));
        service.takeOver(conversation());
        expect(chatApi.claim).toHaveBeenCalledTimes(1);
        expect(changed).toEqual([]);
        expect(service.isPending()).toBe(false);
    });

    it('toasts any other failure without asking', () => {
        chatApi.claim.mockReturnValueOnce(throwError(() => new HttpErrorResponse({ status: 500 })));
        service.takeOver(conversation());
        expect(confirmation.confirm).not.toHaveBeenCalled();
        expect(toast.error).toHaveBeenCalledTimes(1);
        expect(service.isPending()).toBe(false);
    });

    it('releases a conversation to the bot and publishes the row', () => {
        const released = conversation({ mode: 'bot', handoff_at: null });
        chatApi.release.mockReturnValueOnce(of(released));
        service.release(conversation({ mode: 'human', assigned_operator_id: 3 }));
        expect(chatApi.release).toHaveBeenCalledWith('c-1');
        expect(changed).toEqual([released]);
    });

    it('runs one action at a time, wherever it was asked for', () => {
        const pending$ = new Subject<ChatConversation>();
        chatApi.claim.mockReturnValueOnce(pending$);
        service.takeOver(conversation());
        expect(service.isPending()).toBe(true);

        service.release(conversation());
        service.takeOver(conversation({ id: 'c-2' }));
        expect(chatApi.release).not.toHaveBeenCalled();
        expect(chatApi.claim).toHaveBeenCalledTimes(1);

        pending$.next(conversation({ mode: 'human' }));
        pending$.complete();
        expect(service.isPending()).toBe(false);
    });
});
