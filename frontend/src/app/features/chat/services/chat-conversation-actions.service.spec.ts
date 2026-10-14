import { HttpErrorResponse } from '@angular/common/http';
import { signal } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { ConfirmationDialogService } from '@shared/components';
import { of, Subject, throwError } from 'rxjs';

import { ProfileService } from '../../../services/auth/profile.service';
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
    status: 'open',
    close_reason: null,
    closed_at: null,
    closed_by_user_id: null,
    closed_by_name: null,
    ...overrides,
});

const heldByOther = (): HttpErrorResponse =>
    new HttpErrorResponse({ status: 409, error: { code: 'claimed_by_other', message: 'held' } });
const alreadyClosed = (): HttpErrorResponse =>
    new HttpErrorResponse({
        status: 409,
        error: { code: 'conversation_closed', message: 'Conversation is closed', close_reason: 'ended' },
    });
const closedRow = (): ChatConversation =>
    conversation({
        status: 'closed',
        close_reason: 'resolved',
        closed_at: '2026-10-10T11:00:00Z',
        closed_by_user_id: 3,
    });

describe('ChatConversationActionsService', () => {
    let service: ChatConversationActionsService;
    let changed: ChatConversation[];
    const chatApi = { claim: vi.fn(), release: vi.fn(), close: vi.fn(), getConversation: vi.fn() };
    const confirmation = { confirm: vi.fn() };
    const toast = { error: vi.fn() };

    beforeEach(() => {
        vi.clearAllMocks();
        TestBed.configureTestingModule({
            providers: [
                { provide: ChatApiService, useValue: chatApi },
                { provide: ConfirmationDialogService, useValue: confirmation },
                { provide: ToastService, useValue: toast },
                { provide: ProfileService, useValue: { currentUserSignal: signal({ id: 3 }) } },
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

    it('toasts that a conversation is closed when the server refuses an action on it, and publishes it as it is', () => {
        const closedMeanwhile = closedRow();
        chatApi.claim.mockReturnValueOnce(throwError(alreadyClosed));
        chatApi.getConversation.mockReturnValueOnce(of(closedMeanwhile));
        service.takeOver(conversation());
        expect(confirmation.confirm).not.toHaveBeenCalled();
        expect(toast.error).toHaveBeenCalledWith('This conversation is closed.');
        expect(chatApi.getConversation).toHaveBeenCalledWith('c-1');
        expect(changed).toEqual([closedMeanwhile]);
        expect(service.isPending()).toBe(false);
    });

    it('fetches nothing again for any other failure, and publishes nothing when that fetch fails', () => {
        chatApi.release.mockReturnValueOnce(throwError(() => new HttpErrorResponse({ status: 500 })));
        service.release(conversation());
        expect(chatApi.getConversation).not.toHaveBeenCalled();

        chatApi.getConversation.mockReturnValueOnce(throwError(() => new HttpErrorResponse({ status: 500 })));
        service.refresh('c-1');
        expect(changed).toEqual([]);
    });

    describe('Resolve', () => {
        it('closes the conversation without asking and publishes the closed row', () => {
            chatApi.close.mockReturnValueOnce(of(closedRow()));
            service.resolve(conversation({ mode: 'human', assigned_operator_id: 3 }));
            expect(chatApi.close).toHaveBeenCalledWith('c-1');
            expect(confirmation.confirm).not.toHaveBeenCalled();
            expect(changed).toEqual([closedRow()]);
            expect(service.isPending()).toBe(false);
        });

        it('asks before resolving a conversation another operator holds, then closes it with force', () => {
            chatApi.close.mockReturnValueOnce(throwError(heldByOther)).mockReturnValueOnce(of(closedRow()));
            confirmation.confirm.mockReturnValueOnce(of(true));
            service.resolve(conversation({ mode: 'human', assigned_operator_id: 7 }));
            expect(confirmation.confirm).toHaveBeenCalledWith(
                expect.objectContaining({ title: 'Resolve conversation', confirmText: 'Resolve', type: 'danger' })
            );
            expect(chatApi.close).toHaveBeenLastCalledWith('c-1', true);
            expect(changed).toEqual([closedRow()]);
        });
    });

    describe('Close conversation', () => {
        it('asks first, as a danger, and closes nothing when cancelled', () => {
            confirmation.confirm.mockReturnValueOnce(of(false));
            service.closeConversation(conversation());
            expect(confirmation.confirm).toHaveBeenCalledWith(
                expect.objectContaining({
                    title: 'Close conversation',
                    confirmText: 'Close conversation',
                    type: 'danger',
                    message: "The visitor's next message starts a new conversation. A closed one cannot be reopened.",
                })
            );
            expect(chatApi.close).not.toHaveBeenCalled();
            expect(service.isPending()).toBe(false);
        });

        it('closes once confirmed and publishes the closed row', () => {
            confirmation.confirm.mockReturnValueOnce(of(true));
            chatApi.close.mockReturnValueOnce(of(closedRow()));
            service.closeConversation(conversation({ mode: 'human', assigned_operator_id: 3 }));
            expect(chatApi.close).toHaveBeenCalledWith('c-1', false);
            expect(changed).toEqual([closedRow()]);
        });

        it("names another operator's hold in the one confirm and closes over it", () => {
            confirmation.confirm.mockReturnValueOnce(of(true));
            chatApi.close.mockReturnValueOnce(of(closedRow()));
            service.closeConversation(conversation({ mode: 'human', assigned_operator_id: 7 }));
            expect(confirmation.confirm).toHaveBeenCalledTimes(1);
            expect(confirmation.confirm.mock.calls[0][0].message).toContain(
                'Another operator holds this conversation.'
            );
            expect(chatApi.close).toHaveBeenCalledWith('c-1', true);
        });

        it('asks again only for a hold the row did not show', () => {
            confirmation.confirm.mockReturnValueOnce(of(true)).mockReturnValueOnce(of(true));
            chatApi.close.mockReturnValueOnce(throwError(heldByOther)).mockReturnValueOnce(of(closedRow()));
            service.closeConversation(conversation());
            expect(confirmation.confirm).toHaveBeenCalledTimes(2);
            expect(confirmation.confirm.mock.calls[1][0].message).toBe(
                'Another operator holds this conversation. Close it anyway?'
            );
            expect(chatApi.close).toHaveBeenLastCalledWith('c-1', true);
            expect(changed).toEqual([closedRow()]);
        });
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
