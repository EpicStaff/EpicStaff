import { Dialog } from '@angular/cdk/dialog';
import { GlobalPositionStrategy } from '@angular/cdk/overlay';
import { HttpErrorResponse } from '@angular/common/http';
import { signal } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { ConfirmationDialogService } from '@shared/components';
import { of, throwError } from 'rxjs';

import { PhoneLayoutService } from '../../../core/services/phone-layout.service';
import { ToastService } from '../../../services/notifications';
import { ChatBindingsDialogComponent } from '../components/chat-bindings-dialog/chat-bindings-dialog.component';
import {
    MY_DESK_ALIAS_TITLE_ID,
    MyDeskAliasDialogComponent,
} from '../components/my-desk-alias-dialog/my-desk-alias-dialog.component';
import { CHAT_BINDING_DEFAULTS, ChatBinding, ChatMyAliasResult } from '../models/chat.model';
import { ChatApiService } from './chat-api.service';
import { ChatBindingActionsService } from './chat-binding-actions.service';

const binding: ChatBinding = {
    ...CHAT_BINDING_DEFAULTS,
    response_time_seconds: 600,
    on_response_timeout: 'handback',
    handback_message: 'Back to the bot.',
    close_after_seconds: 86_400,
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
    const dialog = { open: vi.fn() };
    const isPhone = signal(false);

    function collect(source: ReturnType<ChatBindingActionsService['pause']>): boolean[] {
        const values: boolean[] = [];
        source.subscribe((value) => values.push(value));
        return values;
    }

    beforeEach(() => {
        vi.clearAllMocks();
        isPhone.set(false);
        TestBed.configureTestingModule({
            providers: [
                { provide: ChatApiService, useValue: chatApi },
                { provide: ConfirmationDialogService, useValue: confirmation },
                { provide: ToastService, useValue: toast },
                { provide: Dialog, useValue: dialog },
                { provide: PhoneLayoutService, useValue: { isPhone } },
            ],
        });
        service = TestBed.inject(ChatBindingActionsService);
    });

    it('opens the create dialog and emits the created desk, or null when the dialog closed without one', () => {
        const results: (ChatBinding | null)[] = [];
        dialog.open.mockReturnValueOnce({ closed: of(binding) });
        service.create().subscribe((created) => results.push(created));
        expect(dialog.open).toHaveBeenCalledWith(
            ChatBindingsDialogComponent,
            expect.objectContaining({ data: { binding: null } })
        );

        dialog.open.mockReturnValueOnce({ closed: of(undefined) });
        service.create().subscribe((created) => results.push(created));
        expect(results).toEqual([binding, null]);
    });

    it("opens a desk's settings and emits once the dialog closes, saved or not", () => {
        let closes = 0;
        dialog.open.mockReturnValueOnce({ closed: of(undefined) });
        service.openSettings(binding).subscribe(() => closes++);
        expect(dialog.open).toHaveBeenCalledWith(
            ChatBindingsDialogComponent,
            expect.objectContaining({ data: { binding } })
        );
        expect(closes).toBe(1);
    });

    it('opens my name on a desk, named by its title, and emits what was saved, or null', () => {
        const saved: ChatMyAliasResult = { binding_id: 'b-1', alias: 'Mike', visible_name: 'Mike' };
        const results: (ChatMyAliasResult | null)[] = [];
        dialog.open.mockReturnValueOnce({ closed: of(saved) }).mockReturnValueOnce({ closed: of(undefined) });

        service.editMyAlias(binding).subscribe((result) => results.push(result));
        service.editMyAlias(binding).subscribe((result) => results.push(result));

        expect(dialog.open).toHaveBeenCalledWith(
            MyDeskAliasDialogComponent,
            expect.objectContaining({ data: { binding }, ariaLabelledBy: MY_DESK_ALIAS_TITLE_ID })
        );
        expect(results).toEqual([saved, null]);
    });

    it('opens the desk dialogs at their width on wider screens, and as full-width sheets from the bottom on phones', () => {
        dialog.open.mockReturnValue({ closed: of(undefined) });
        service.create().subscribe();
        service.editMyAlias(binding).subscribe();
        expect(dialog.open.mock.calls.map(([, config]) => config.width)).toEqual(['720px', '480px']);
        expect(dialog.open.mock.calls.every(([, config]) => !config.positionStrategy)).toBe(true);

        dialog.open.mockClear();
        isPhone.set(true);
        service.openSettings(binding).subscribe();
        service.editMyAlias(binding).subscribe();
        for (const [, config] of dialog.open.mock.calls) {
            expect(config).toEqual(expect.objectContaining({ width: '100vw', maxWidth: '100vw' }));
            expect(config.positionStrategy).toBeInstanceOf(GlobalPositionStrategy);
        }
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
                title: 'Pause the desk?',
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
