import { DIALOG_DATA, DialogRef } from '@angular/cdk/dialog';
import { HttpErrorResponse } from '@angular/common/http';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { By } from '@angular/platform-browser';
import { ConfirmationDialogService } from '@shared/components';
import { ActionCode, ResourceCode } from '@shared/models';
import { of, Subject, throwError } from 'rxjs';

import { PermissionsService } from '../../../../services/auth/permissions.service';
import { ToastService } from '../../../../services/notifications';
import { FlowsApiService } from '../../../flows/services/flows-api.service';
import { CHAT_BINDING_DEFAULTS, ChatBinding, ChatBindingLimits, ChatBindingWithSecret } from '../../models/chat.model';
import { ChatApiService } from '../../services/chat-api.service';
import { ChatBindingsDialogComponent, ChatBindingsDialogData } from './chat-bindings-dialog.component';

class ResizeObserverStub {
    observe(): void {}
    unobserve(): void {}
    disconnect(): void {}
}

const binding = (overrides: Partial<ChatBinding>): ChatBinding => ({
    id: 'b-1',
    org_id: 1,
    graph_id: 5,
    name: 'Support',
    bot_display_name: 'Support',
    public_key: 'pk-1',
    is_active: true,
    broken_reason: null,
    contract_errors: [],
    created_at: '',
    updated_at: '',
    ...CHAT_BINDING_DEFAULTS,
    token_budget_per_conversation: 200_000,
    daily_token_budget: 1_000_000,
    ...overrides,
});

const LIMITS: ChatBindingLimits = {
    defaults: { token_budget_per_conversation: 50_000, daily_token_budget: 1_000_000 },
    caps: { token_budget_per_conversation: 200_000, daily_token_budget: 5_000_000 },
};

describe('ChatBindingsDialogComponent', () => {
    let fixture: ComponentFixture<ChatBindingsDialogComponent>;
    const chatApi = {
        getBindings: vi.fn(() => of([binding({})])),
        getBindingLimits: vi.fn(() => of(LIMITS)),
        createBinding: vi.fn(),
        updateBinding: vi.fn(),
        deleteBinding: vi.fn(),
        rotateKey: vi.fn(),
        getSnippet: vi.fn(),
        checkContract: vi.fn(),
        pauseBinding: vi.fn(),
        resumeBinding: vi.fn(),
    };
    const permissions: { can: (resource: ResourceCode, action?: ActionCode) => boolean } = {
        can: (resource) => resource === ResourceCode.Chats,
    };

    const unknownFlow = () =>
        throwError(
            () =>
                new HttpErrorResponse({
                    status: 400,
                    error: { code: 'unknown_flow', message: 'The flow does not exist.' },
                })
        );

    const dialogData: ChatBindingsDialogData = { binding: null };

    /** Opens the dialog for a binding's settings, or in create mode for null. */
    function open(edited: ChatBinding | null): ChatBindingsDialogComponent {
        dialogData.binding = edited;
        fixture = TestBed.createComponent(ChatBindingsDialogComponent);
        fixture.detectChanges();
        return fixture.componentInstance;
    }

    function text(selector: string): string[] {
        const host: HTMLElement = fixture.nativeElement;
        return Array.from(host.querySelectorAll(selector)).map(
            (node) => node.textContent?.replace(/\s+/g, ' ').trim() ?? ''
        );
    }

    beforeEach(() => {
        vi.stubGlobal('ResizeObserver', ResizeObserverStub);
        vi.clearAllMocks();
        chatApi.getBindings.mockReturnValue(of([binding({})]));
        chatApi.getBindingLimits.mockReturnValue(of(LIMITS));
        chatApi.checkContract.mockReturnValue(of({ contract_errors: [] }));
        TestBed.configureTestingModule({
            imports: [ChatBindingsDialogComponent],
            providers: [
                { provide: ChatApiService, useValue: chatApi },
                { provide: FlowsApiService, useValue: { getGraphsLight: () => of([{ id: 5, name: 'Support flow' }]) } },
                { provide: DialogRef, useValue: { close: vi.fn() } },
                { provide: ConfirmationDialogService, useValue: { confirm: vi.fn(), confirmDelete: vi.fn() } },
                { provide: ToastService, useValue: { error: vi.fn(), success: vi.fn(), warning: vi.fn() } },
                { provide: PermissionsService, useValue: permissions },
                { provide: DIALOG_DATA, useValue: dialogData },
            ],
        });
    });

    afterEach(() => vi.unstubAllGlobals());

    it('patches only the fields that changed', () => {
        chatApi.updateBinding.mockReturnValue(of(binding({ name: 'Sales' })));
        const component = open(binding({}));
        component.form.controls.name.setValue('Sales');
        component.submit();
        expect(chatApi.updateBinding).toHaveBeenCalledWith('b-1', { name: 'Sales' });
    });

    it('checks the contract of a picked flow live and shows a missing flow as an error', () => {
        const component = open(null);
        fixture.detectChanges();
        chatApi.checkContract.mockReturnValueOnce(of({ contract_errors: ['end node lacks reply'] }));
        component.form.controls.graph_id.setValue(5);
        fixture.detectChanges();
        expect(chatApi.checkContract).toHaveBeenCalledWith(5);
        expect(text('.bindings-dialog__contract-error')).toEqual(['end node lacks reply']);

        chatApi.checkContract.mockReturnValueOnce(unknownFlow());
        component.form.controls.graph_id.setValue(6);
        fixture.detectChanges();
        expect(text('.bindings-dialog__contract-error')).toEqual(['The flow does not exist.']);

        component.form.controls.graph_id.setValue(null);
        fixture.detectChanges();
        expect(text('.bindings-dialog__contract-error')).toEqual([]);
    });

    it('refuses a whitespace-only binding name and says so under Name', () => {
        const component = open(null);
        component.form.patchValue({ name: '   ', graph_id: 5 });
        component.submit();
        fixture.detectChanges();
        expect(chatApi.createBinding).not.toHaveBeenCalled();
        expect(component.form.controls.name.valid).toBe(false);
        expect(component.textFieldError('name')).toBe('Required');
        expect(component.activeTab()).toBe('general');
    });

    it('drops the check of a flow that was picked again before it answered', () => {
        const component = open(null);
        const slow$ = new Subject<{ contract_errors: string[] }>();
        chatApi.checkContract.mockReturnValueOnce(slow$).mockReturnValueOnce(of({ contract_errors: [] }));
        component.form.controls.graph_id.setValue(5);
        component.form.controls.graph_id.setValue(6);
        expect(slow$.observed).toBe(false);
        expect(component.contractErrors()).toEqual([]);
    });

    it('has no Active toggle and posts both display names, the bot one following the name until edited', () => {
        chatApi.createBinding.mockReturnValue(of({ ...binding({ id: 'b-2' }), identity_secret: null }));
        const component = open(null);
        fixture.detectChanges();
        expect(text('app-toggle-switch')).not.toContain('Active');
        expect(component.form.contains('is_active')).toBe(false);

        component.form.controls.name.setValue('Portal');
        expect(component.form.controls.bot_display_name.value).toBe('Portal');
        component.form.controls.name.setValue('x'.repeat(70));
        expect(component.form.controls.bot_display_name.value).toBe('x'.repeat(64));
        component.form.controls.bot_display_name.setValue('Ava');
        component.form.controls.bot_display_name.markAsDirty();
        component.form.controls.name.setValue('Portal');
        expect(component.form.controls.bot_display_name.value).toBe('Ava');

        component.form.controls.graph_id.setValue(5);
        component.submit();
        const body = chatApi.createBinding.mock.calls[0][0];
        expect(body).not.toHaveProperty('is_active');
        expect(body).toEqual(expect.objectContaining({ bot_display_name: 'Ava', operator_display_name: 'Support' }));
    });

    it('never fills the bot name from the name while editing, and requires both names within 64 characters', () => {
        const component = open(binding({ bot_display_name: 'Ava' }));
        component.form.controls.name.setValue('Sales');
        expect(component.form.controls.bot_display_name.value).toBe('Ava');

        for (const field of ['bot_display_name', 'operator_display_name'] as const) {
            const control = component.form.controls[field];
            control.setValue('');
            expect(control.valid).toBe(false);
            control.setValue('   ');
            expect(control.valid).toBe(false);
            control.setValue('x'.repeat(65));
            control.markAsTouched();
            expect(component.textFieldError(field)).toBe('At most 64 characters');
            control.setValue('x'.repeat(64));
            expect(control.valid).toBe(true);
        }
    });

    it('warns when a save comes back paused on a failing contract', () => {
        chatApi.updateBinding.mockReturnValue(
            of(binding({ name: 'Sales', is_active: false, contract_errors: ['end node lacks reply'] }))
        );
        const component = open(binding({}));
        component.form.controls.name.setValue('Sales');
        component.submit();
        expect(TestBed.inject(ToastService).warning).toHaveBeenCalledWith(
            'Saved but paused: the flow does not meet the chat contract.'
        );
        expect(TestBed.inject(DialogRef).close).toHaveBeenCalled();
    });

    it('shows the identity secret once after creating a signed binding', () => {
        const created: ChatBindingWithSecret = {
            ...binding({ id: 'b-2', identity_mode: 'signed' }),
            identity_secret: 'shh',
        };
        chatApi.createBinding.mockReturnValue(of(created));
        const component = open(null);
        component.form.patchValue({ name: 'Portal', graph_id: 5, identity_mode: 'signed' });
        component.submit();
        fixture.detectChanges();
        expect(component.revealedSecret()).toBe('shh');
        expect(fixture.nativeElement.querySelector('app-copy-field')).not.toBeNull();
        expect(fixture.nativeElement.querySelector('form')).toBeNull();
        expect(TestBed.inject(DialogRef).close).not.toHaveBeenCalled();

        (fixture.nativeElement.querySelector('.bindings-dialog__actions button') as HTMLButtonElement).click();
        expect(TestBed.inject(DialogRef).close).toHaveBeenCalled();
    });

    it('prefills the budgets on create from the server defaults and posts them', () => {
        chatApi.createBinding.mockReturnValue(of({ ...binding({ id: 'b-2' }), identity_secret: null }));
        const component = open(null);
        expect(component.form.controls.token_budget_per_conversation.value).toBe(50_000);
        expect(component.form.controls.daily_token_budget.value).toBe(1_000_000);
        component.form.patchValue({ name: 'Portal', graph_id: 5 });
        component.submit();
        expect(chatApi.createBinding).toHaveBeenCalledWith(
            expect.objectContaining({
                name: 'Portal',
                token_budget_per_conversation: 50_000,
                daily_token_budget: 1_000_000,
            })
        );
    });

    it('requires both budgets on create', () => {
        const component = open(null);
        component.form.patchValue({ name: 'Portal', graph_id: 5, daily_token_budget: null });
        expect(component.form.controls.daily_token_budget.hasError('required')).toBe(true);
        expect(component.form.valid).toBe(false);
        component.submit();
        expect(chatApi.createBinding).not.toHaveBeenCalled();
        expect(component.activeTab()).toBe('limits');
    });

    it('splits the form into tabs and Save opens the first tab with an invalid field', () => {
        open(null);
        const host: HTMLElement = fixture.nativeElement;
        const visibleTabs = () =>
            Array.from(host.querySelectorAll<HTMLElement>('.bindings-dialog__tab')).map((tab) => !tab.hidden);
        expect(text('app-tab-button')).toEqual(['General', 'Limits', 'Handoff']);
        expect(visibleTabs()).toEqual([true, false, false]);

        (host.querySelectorAll('app-tab-button button')[2] as HTMLButtonElement).click();
        fixture.detectChanges();
        expect(visibleTabs()).toEqual([false, false, true]);

        // The name is still empty: Save stays clickable so it can lead the user to it.
        const save = Array.from(host.querySelectorAll<HTMLButtonElement>('.bindings-dialog__actions button')).find(
            (button) => button.textContent?.trim() === 'Save'
        ) as HTMLButtonElement;
        expect(save.disabled).toBe(false);
        save.click();
        fixture.detectChanges();
        expect(chatApi.createBinding).not.toHaveBeenCalled();
        expect(visibleTabs()).toEqual([true, false, false]);
    });

    it('caps each budget input at the deployment cap and names the default and cap in its tooltip', () => {
        open(null);
        fixture.detectChanges();
        const input = (field: string) =>
            fixture.debugElement.query(By.css(`app-input-number[formControlName="${field}"]`)).componentInstance as {
                max: () => number | null;
                tooltipText: () => string;
            };
        expect(input('token_budget_per_conversation').max()).toBe(200_000);
        expect(input('daily_token_budget').max()).toBe(5_000_000);
        expect(input('daily_token_budget').tooltipText()).toContain('Default 1,000,000, at most 5,000,000');
    });

    it('blocks a budget above the deployment cap locally with the cap message', () => {
        const component = open(binding({}));
        fixture.detectChanges();
        component.form.controls.daily_token_budget.markAsDirty();
        component.form.controls.daily_token_budget.setValue(5_000_001);
        fixture.detectChanges();
        expect(component.budgetCapMessage('daily_token_budget')).toBe('At most 5,000,000 on this deployment');
        expect(text('.input__message--error')).toEqual(['At most 5,000,000 on this deployment']);
        component.submit();
        expect(chatApi.updateBinding).not.toHaveBeenCalled();

        component.form.controls.daily_token_budget.setValue(5_000_000);
        expect(component.form.valid).toBe(true);
    });

    it('does not block other edits on a stored budget above a lowered cap, only a typed one', () => {
        chatApi.updateBinding.mockReturnValue(of(binding({ name: 'Sales' })));
        const component = open(binding({ daily_token_budget: 9_000_000 }));
        fixture.detectChanges();
        component.form.controls.name.setValue('Sales');
        expect(component.budgetCapMessage('daily_token_budget')).toBe('');
        component.submit();
        expect(chatApi.updateBinding).toHaveBeenCalledWith('b-1', { name: 'Sales' });

        chatApi.updateBinding.mockClear();
        const again = open(binding({ daily_token_budget: 9_000_000 }));
        again.form.controls.daily_token_budget.markAsDirty();
        again.form.controls.daily_token_budget.setValue(8_000_000);
        expect(again.budgetCapMessage('daily_token_budget')).toBe('At most 5,000,000 on this deployment');
        again.submit();
        expect(chatApi.updateBinding).not.toHaveBeenCalled();
    });

    it('leaves the budgets empty and required when the limits failed to load', () => {
        chatApi.getBindingLimits.mockReturnValue(throwError(() => new HttpErrorResponse({ status: 500 })));
        const component = open(null);
        expect(TestBed.inject(ToastService).error).toHaveBeenCalled();
        component.form.patchValue({ name: 'Portal', graph_id: 5 });
        expect(component.form.controls.token_budget_per_conversation.value).toBeNull();
        expect(component.form.controls.token_budget_per_conversation.hasError('required')).toBe(true);
        expect(component.form.valid).toBe(false);
    });

    it.each([
        { field: 'daily_token_budget' },
        { field: 'unknown_field', max: 50_000_000 },
        { max: 50_000_000 },
        { field: 'daily_token_budget', max: null },
    ])('falls back to the error banner for a malformed budget_above_cap body %o', (extra) => {
        chatApi.updateBinding.mockReturnValue(
            throwError(
                () =>
                    new HttpErrorResponse({
                        status: 400,
                        error: { code: 'budget_above_cap', message: 'Above the cap.', ...extra },
                    })
            )
        );
        const component = open(binding({}));
        // Under the cap the dialog knows, so only the server can refuse it.
        component.form.controls.daily_token_budget.setValue(4_000_000);
        component.submit();
        expect(component.errorMessage()).not.toBeNull();
        expect(component.form.controls.daily_token_budget.valid).toBe(true);
        expect(component.form.controls.token_budget_per_conversation.valid).toBe(true);
    });

    it('shows budget_above_cap on the refused budget input with the deployment max', () => {
        chatApi.updateBinding.mockReturnValue(
            throwError(
                () =>
                    new HttpErrorResponse({
                        status: 400,
                        error: {
                            code: 'budget_above_cap',
                            message: 'Above the cap.',
                            field: 'daily_token_budget',
                            max: 3_000_000,
                        },
                    })
            )
        );
        const component = open(binding({}));
        // Render the form first, as the user sees it: binding formControlName re-validates and would clear the error.
        fixture.detectChanges();
        // Under the cap the dialog knows, so only the server can refuse it.
        component.form.controls.daily_token_budget.setValue(4_000_000);
        component.submit();
        fixture.detectChanges();
        expect(component.budgetCapMessage('daily_token_budget')).toBe('At most 3,000,000 on this deployment');
        expect(component.budgetCapMessage('token_budget_per_conversation')).toBe('');
        expect(component.errorMessage()).toBeNull();
        expect(component.activeTab()).toBe('limits');
        expect(text('.input__message--error')).toEqual(['At most 3,000,000 on this deployment']);

        component.form.controls.daily_token_budget.setValue(2_000_000);
        expect(component.budgetCapMessage('daily_token_budget')).toBe('');
    });
    it('fills the budgets with the server defaults when the limits arrive after a create dialog opened', () => {
        const limits$ = new Subject<ChatBindingLimits>();
        chatApi.getBindingLimits.mockReturnValue(limits$);
        const component = open(null);
        expect(component.form.controls.daily_token_budget.value).toBeNull();
        limits$.next(LIMITS);
        fixture.detectChanges();
        expect(component.form.controls.token_budget_per_conversation.value).toBe(50_000);
        expect(component.form.controls.daily_token_budget.value).toBe(1_000_000);
    });

    it('titles the dialog by mode and offers Rotate key only for an existing binding', () => {
        open(null);
        expect(text('.bindings-dialog__title')).toEqual(['New chat binding']);
        expect(text('.bindings-dialog__actions app-button')).not.toContain('Rotate key');

        open(binding({}));
        expect(text('.bindings-dialog__title')).toEqual(['Edit chat binding']);
        expect(text('.bindings-dialog__actions app-button')).toContain('Rotate key');
    });

    it('rotates the key after a danger confirm and diffs later saves against the rotated binding', () => {
        const confirmation = TestBed.inject(ConfirmationDialogService);
        vi.mocked(confirmation.confirm).mockReturnValue(of(true));
        chatApi.rotateKey.mockReturnValue(of(binding({ public_key: 'pk-2' })));
        const component = open(binding({}));
        component.rotateKey();
        expect(vi.mocked(confirmation.confirm).mock.calls[0][0]).toEqual(
            expect.objectContaining({ title: 'Rotate public key', type: 'danger' })
        );
        expect(chatApi.rotateKey).toHaveBeenCalledWith('b-1');
        expect(component.binding()?.public_key).toBe('pk-2');
        expect(TestBed.inject(ToastService).success).toHaveBeenCalledWith('Public key rotated');
    });
});
