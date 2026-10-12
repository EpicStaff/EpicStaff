import { HttpErrorResponse } from '@angular/common/http';
import { TestBed } from '@angular/core/testing';
import { ConfirmationDialogService } from '@shared/components';
import { of, throwError } from 'rxjs';

import { ToastService } from '../../../services/notifications';
import { CHAT_BINDING_DEFAULTS, ChatBinding } from '../models/chat.model';
import { ChatApiService } from './chat-api.service';
import { ChatBindingActionsService } from './chat-binding-actions.service';

const binding: ChatBinding = {
    ...CHAT_BINDING_DEFAULTS,
    id: 'b-1',
    org_id: 1,
    graph_id: 5,
    name: 'Q&A',
    bot_display_name: 'Q&A',
    public_key: 'pk',
    is_active: true,
    token_budget_per_conversation: 1000,
    daily_token_budget: 1_000_000,
    broken_reason: null,
    contract_errors: [],
    created_at: '',
    updated_at: '',
};

describe('ChatBindingActionsService', () => {
    let service: ChatBindingActionsService;
    const chatApi = { pauseBinding: vi.fn(), resumeBinding: vi.fn(), deleteBinding: vi.fn(), getSnippet: vi.fn() };
    const confirmation = { confirm: vi.fn(), confirmDelete: vi.fn() };
    const toast = { error: vi.fn(), success: vi.fn() };

    function collect(source: ReturnType<ChatBindingActionsService['pause']>): boolean[] {
        const values: boolean[] = [];
        source.subscribe((value) => values.push(value));
        return values;
    }

    beforeEach(() => {
        vi.clearAllMocks();
        TestBed.configureTestingModule({
            providers: [
                { provide: ChatApiService, useValue: chatApi },
                { provide: ConfirmationDialogService, useValue: confirmation },
                { provide: ToastService, useValue: toast },
            ],
        });
        service = TestBed.inject(ChatBindingActionsService);
    });

    it('pauses only after a danger confirm naming the escaped binding, and sends nothing when cancelled', () => {
        confirmation.confirm.mockReturnValueOnce(of(false));
        expect(collect(service.pause(binding))).toEqual([]);
        expect(chatApi.pauseBinding).not.toHaveBeenCalled();

        confirmation.confirm.mockReturnValueOnce(of(true));
        chatApi.pauseBinding.mockReturnValue(of({ ...binding, is_active: false }));
        expect(collect(service.pause(binding))).toEqual([true]);
        expect(chatApi.pauseBinding).toHaveBeenCalledWith('b-1');
        expect(confirmation.confirm.mock.calls[1][0]).toEqual(
            expect.objectContaining({
                title: 'Pause the binding?',
                confirmText: 'Pause',
                type: 'danger',
                message: expect.stringContaining('Q&amp;A'),
            })
        );
    });

    it('resumes without a confirm and reports a refused resume as a change after toasting it', () => {
        chatApi.resumeBinding.mockReturnValueOnce(of(binding));
        expect(collect(service.resume(binding))).toEqual([true]);
        expect(confirmation.confirm).not.toHaveBeenCalled();

        chatApi.resumeBinding.mockReturnValueOnce(
            throwError(() => new HttpErrorResponse({ status: 400, error: { code: 'contract_failed', message: 'No.' } }))
        );
        expect(collect(service.resume(binding))).toEqual([true]);
        expect(toast.error).toHaveBeenCalled();

        chatApi.resumeBinding.mockReturnValueOnce(throwError(() => new HttpErrorResponse({ status: 500 })));
        expect(collect(service.resume(binding))).toEqual([]);
        expect(toast.error).toHaveBeenCalledTimes(2);
    });

    it('deletes after confirmDelete with the raw name, and toasts a failure without reporting a change', () => {
        confirmation.confirmDelete.mockReturnValue(of(true));
        chatApi.deleteBinding.mockReturnValueOnce(of(undefined));
        expect(collect(service.delete(binding))).toEqual([true]);
        expect(confirmation.confirmDelete).toHaveBeenCalledWith('Q&A');

        chatApi.deleteBinding.mockReturnValueOnce(throwError(() => new HttpErrorResponse({ status: 500 })));
        expect(collect(service.delete(binding))).toEqual([]);
        expect(toast.error).toHaveBeenCalled();
    });
});
