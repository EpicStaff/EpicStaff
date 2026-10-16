import { DIALOG_DATA, DialogRef } from '@angular/cdk/dialog';
import { HttpErrorResponse } from '@angular/common/http';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { FormControl } from '@angular/forms';
import { By } from '@angular/platform-browser';
import { ConfirmationDialogService, InputNumberComponent } from '@shared/components';
import { ActionCode, ResourceCode } from '@shared/models';
import { of, Subject, throwError } from 'rxjs';

import { PermissionsService } from '../../../../services/auth/permissions.service';
import { ToastService } from '../../../../services/notifications';
import { FlowsApiService } from '../../../flows/services/flows-api.service';
import {
    CHAT_BINDING_DEFAULTS,
    ChatBinding,
    ChatBindingLimits,
    ChatBindingWithSecret,
    ChatContractCheck,
    ChatContractMissing,
} from '../../models/chat.model';
import { ChatApiService } from '../../services/chat-api.service';
import { ChatContractFixComponent } from '../chat-contract-fix/chat-contract-fix.component';
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
    response_time_seconds: 600,
    on_response_timeout: 'handback',
    handback_message: 'Back to the bot.',
    close_after_seconds: 86_400,
    token_budget_per_conversation: 200_000,
    daily_token_budget: 1_000_000,
    ...overrides,
});

const NOTHING_MISSING: ChatContractMissing = {
    missing_start_node: false,
    missing_end_node: false,
    start_variables: [],
    end_outputs: [],
};

const contractCheck = (
    contract_errors: string[] = [],
    contract_missing: ChatContractMissing = NOTHING_MISSING
): ChatContractCheck => ({ contract_errors, contract_missing });

const LIMITS: ChatBindingLimits = {
    defaults: {
        token_budget_per_conversation: 50_000,
        daily_token_budget: 1_000_000,
        // 10 minutes, then hand back; close after 24 hours.
        response_time_seconds: 600,
        on_response_timeout: 'handback',
        handback_message: 'Nobody could answer in time. The bot is back.',
        close_after_seconds: 86_400,
        style: 'support',
    },
    // One day; 30 days.
    caps: {
        token_budget_per_conversation: 200_000,
        daily_token_budget: 5_000_000,
        response_time_seconds: 86_400,
        close_after_seconds: 2_592_000,
    },
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
        chatApi.checkContract.mockReturnValue(of(contractCheck()));
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
        chatApi.checkContract.mockReturnValueOnce(of(contractCheck(['end node lacks reply'])));
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

    it('offers the fix for what the picked flow lacks, and checks the flow again once it is applied', () => {
        const component = open(null);
        const missing = { ...NOTHING_MISSING, start_variables: ['chat_history'] };
        chatApi.checkContract.mockReturnValueOnce(of(contractCheck(['start node lacks chat_history'], missing)));
        component.form.controls.graph_id.setValue(5);
        fixture.detectChanges();
        // Without the right to edit flows the panel only says what is missing and who can apply it.
        const [panel] = text('app-chat-contract-fix');
        expect(panel).toContain('Start node Domain variables: chat_history');
        expect(panel).toContain('Someone who can edit this flow must apply these changes.');

        fixture.debugElement.query(By.directive(ChatContractFixComponent)).triggerEventHandler('applied');
        fixture.detectChanges();

        expect(chatApi.checkContract).toHaveBeenLastCalledWith(5);
        expect(text('.bindings-dialog__contract-error')).toEqual([]);
        expect(text('app-chat-contract-fix')).toEqual([]);
    });

    it('keeps the errors and the fix together when checking the flow again fails', () => {
        const component = open(null);
        const missing = { ...NOTHING_MISSING, start_variables: ['chat_history'] };
        chatApi.checkContract.mockReturnValueOnce(of(contractCheck(['start node lacks chat_history'], missing)));
        component.form.controls.graph_id.setValue(5);
        fixture.detectChanges();

        chatApi.checkContract.mockReturnValueOnce(throwError(() => new HttpErrorResponse({ status: 502 })));
        fixture.debugElement.query(By.directive(ChatContractFixComponent)).triggerEventHandler('applied');
        fixture.detectChanges();

        expect(text('.bindings-dialog__contract-error')).toEqual(['start node lacks chat_history']);
        expect(text('app-chat-contract-fix').length).toBe(1);
    });

    it('drops the fix of a flow as soon as another one is picked', () => {
        const component = open(null);
        const missing = { ...NOTHING_MISSING, end_outputs: ['reply'] };
        chatApi.checkContract.mockReturnValueOnce(of(contractCheck(['end node lacks reply'], missing)));
        component.form.controls.graph_id.setValue(5);
        fixture.detectChanges();
        expect(text('app-chat-contract-fix').length).toBe(1);

        chatApi.checkContract.mockReturnValueOnce(new Subject<ChatContractCheck>());
        component.form.controls.graph_id.setValue(6);
        fixture.detectChanges();

        expect(text('app-chat-contract-fix')).toEqual([]);
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
        const slow$ = new Subject<ChatContractCheck>();
        chatApi.checkContract.mockReturnValueOnce(slow$).mockReturnValueOnce(of(contractCheck()));
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
        // Cut by characters: 64 emoji, not 32 and a half.
        const rocket = String.fromCodePoint(0x1f680);
        component.form.controls.name.setValue(rocket.repeat(70));
        expect(component.form.controls.bot_display_name.value).toBe(rocket.repeat(64));
        expect(component.form.controls.bot_display_name.valid).toBe(true);
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
            // As typing does.
            control.markAsDirty();
            control.setValue('');
            expect(control.valid).toBe(false);
            control.setValue('   ');
            expect(control.valid).toBe(false);
            // Blank to the service's strip too, which trim() would not strip.
            control.setValue(String.fromCodePoint(0x1c, 0x85));
            expect(control.valid).toBe(false);
            control.setValue('x'.repeat(65));
            control.markAsTouched();
            expect(component.textFieldError(field)).toBe('Use at most 64 characters.');
            control.setValue('x'.repeat(64));
            expect(control.valid).toBe(true);
            // Characters, not UTF-16 units.
            control.setValue(String.fromCodePoint(0x1f600).repeat(64));
            expect(control.valid).toBe(true);
        }
    });

    describe("the service's rules for the names visitors see", () => {
        const around = (codePoint: number): string => `Sup${String.fromCodePoint(codePoint)}port`;
        const reason = (codePoint: string): string =>
            `Remove the invisible or control character U+${codePoint}: visitors would not see it.`;

        it('refuses a typed name with a control, format or filler character, naming it, on either name field', () => {
            const component = open(binding({}));
            for (const field of ['bot_display_name', 'operator_display_name'] as const) {
                const control = component.form.controls[field];
                control.markAsDirty();
                control.markAsTouched();
                for (const [codePoint, name] of [
                    [0x202e, '202E'],
                    [0x200b, '200B'],
                    [0x3164, '3164'],
                    [0xfe00, 'FE00'],
                    [0xe0041, 'E0041'],
                ] as const) {
                    control.setValue(around(codePoint));
                    expect(component.textFieldError(field)).toBe(reason(name));
                }
            }
            component.submit();
            expect(chatApi.updateBinding).not.toHaveBeenCalled();
        });

        it('keeps the joiner and variation selectors 15 and 16 that emoji need', () => {
            const component = open(binding({}));
            const control = component.form.controls.bot_display_name;
            control.markAsDirty();
            control.setValue(`Ava ${String.fromCodePoint(0x1f469, 0x200d, 0x1f4bb, 0x2764, 0xfe0f, 0x2764, 0xfe0e)}`);
            expect(control.valid).toBe(true);
        });

        it('lets other edits through when a name stored before the rules breaks them, until that name is typed in', () => {
            chatApi.updateBinding.mockReturnValue(of(binding({ name: 'Sales' })));
            const stored = around(0x200b);
            const component = open(binding({ bot_display_name: stored }));
            expect(component.form.controls.bot_display_name.valid).toBe(true);
            component.form.controls.name.setValue('Sales');
            component.submit();
            expect(chatApi.updateBinding).toHaveBeenCalledWith('b-1', { name: 'Sales' });

            const control = component.form.controls.bot_display_name;
            control.markAsDirty();
            control.setValue(`${stored}!`);
            expect(control.hasError('publicName')).toBe(true);
        });

        it("checks a new desk's names from the start, the bot name taken from the desk name included", () => {
            const component = open(null);
            component.form.controls.name.setValue(around(0x202e));
            expect(component.form.controls.bot_display_name.hasError('publicName')).toBe(true);
        });
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

    it('closes with the binding it created, without the identity secret, and with nothing when nothing was saved', () => {
        const close = vi.mocked(TestBed.inject(DialogRef).close);
        const component = open(null);
        component.close();
        expect(close).toHaveBeenLastCalledWith(undefined);

        chatApi.createBinding.mockReturnValue(
            of({ ...binding({ id: 'b-2', identity_mode: 'signed' }), identity_secret: 'shh' })
        );
        component.form.patchValue({ name: 'Portal', graph_id: 5, identity_mode: 'signed' });
        component.submit();
        component.close();
        const result = close.mock.lastCall?.[0] as ChatBinding;
        expect(result.id).toBe('b-2');
        expect('identity_secret' in result).toBe(false);
    });

    it('closes with the created binding at once when no secret is issued', () => {
        chatApi.createBinding.mockReturnValue(of({ ...binding({ id: 'b-3' }), identity_secret: null }));
        const component = open(null);
        component.form.patchValue({ name: 'Portal', graph_id: 5 });
        component.submit();
        expect(TestBed.inject(DialogRef).close).toHaveBeenCalledWith(expect.objectContaining({ id: 'b-3' }));
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
        expect(text('app-tab-button')).toEqual(['General', 'Limits', 'Handoff', 'Inactivity']);
        expect(visibleTabs()).toEqual([true, false, false, false]);

        (host.querySelectorAll('app-tab-button button')[2] as HTMLButtonElement).click();
        fixture.detectChanges();
        expect(visibleTabs()).toEqual([false, false, true, false]);

        // The name is still empty: Save stays clickable so it can lead the user to it.
        const save = Array.from(host.querySelectorAll<HTMLButtonElement>('.bindings-dialog__actions button')).find(
            (button) => button.textContent?.trim() === 'Save'
        ) as HTMLButtonElement;
        expect(save.disabled).toBe(false);
        save.click();
        fixture.detectChanges();
        expect(chatApi.createBinding).not.toHaveBeenCalled();
        expect(visibleTabs()).toEqual([true, false, false, false]);
    });

    describe('style and inactivity rules', () => {
        const radios = (): HTMLInputElement[] =>
            Array.from(
                (fixture.nativeElement as HTMLElement).querySelectorAll<HTMLInputElement>('input[type="radio"]')
            );
        const inputNumber = (label: string) =>
            fixture.debugElement
                .queryAll(By.css('app-input-number'))
                .map((element) => element.componentInstance as InputNumberComponent)
                .find((input) => input.label() === label);
        const showInactivity = (component: ChatBindingsDialogComponent): void => {
            component.activeTab.set('inactivity');
            fixture.detectChanges();
        };

        it('asks for the style on create as two native radios in a group, Support preselected, and sends it', () => {
            chatApi.createBinding.mockReturnValue(of({ ...binding({ id: 'b-2' }), identity_secret: null }));
            const component = open(null);
            fixture.detectChanges();
            const fieldset = (fixture.nativeElement as HTMLElement).querySelector('fieldset.bindings-dialog__style')!;
            expect(fieldset.querySelector('legend')?.textContent?.trim()).toBe('Style');
            const textOf = (id: string | null): string | undefined =>
                id ? document.getElementById(id)?.textContent?.trim() : undefined;
            // Named by the title alone, described by the line: the line is read once.
            expect(radios().map((radio) => [textOf(radio.getAttribute('aria-labelledby')), radio.checked])).toEqual([
                ['Support', true],
                ['Ongoing', false],
            ]);
            expect(textOf(radios()[1].getAttribute('aria-describedby'))).toContain('never closes by itself');
            // One group: the same name in the same form, so the browser gives it one Tab stop and the arrow keys
            // (which jsdom does not move between radios, so they are not pressed here).
            expect(radios().map((radio) => radio.name)).toEqual(['style', 'style']);
            expect(radios()[0].form).not.toBeNull();
            expect(radios()[1].form).toBe(radios()[0].form);

            component.form.patchValue({ name: 'Portal', graph_id: 5 });
            component.submit();
            expect(chatApi.createBinding).toHaveBeenCalledWith(expect.objectContaining({ style: 'support' }));

            radios()[1].click();
            fixture.detectChanges();
            expect(component.form.controls.style.value).toBe('ongoing');
        });

        it("fills the rules on create from the server's defaults, typed in minutes and hours, and posts them in seconds", () => {
            chatApi.createBinding.mockReturnValue(of({ ...binding({ id: 'b-2' }), identity_secret: null }));
            const component = open(null);
            const controls = component.form.controls;
            expect(controls.response_time_minutes.value).toBe(10);
            expect(controls.on_response_timeout.value).toBe('handback');
            expect(controls.handback_message.value).toBe('Nobody could answer in time. The bot is back.');
            expect(controls.close_after_hours.value).toBe(24);

            component.form.patchValue({ name: 'Portal', graph_id: 5 });
            component.submit();
            expect(chatApi.createBinding).toHaveBeenCalledWith(
                expect.objectContaining({
                    response_time_seconds: 600,
                    on_response_timeout: 'handback',
                    handback_message: 'Nobody could answer in time. The bot is back.',
                    close_after_seconds: 86_400,
                })
            );
            const body = chatApi.createBinding.mock.calls[0][0];
            expect(body).not.toHaveProperty('response_time_minutes');
            expect(body).not.toHaveProperty('close_after_hours');
        });

        it('names the default and the cap of each duration in its tooltip and caps its input', () => {
            open(null);
            showInactivity(fixture.componentInstance);
            const responseTime = inputNumber('Response time (minutes)')!;
            expect(responseTime.max()).toBe(1440);
            expect(responseTime.tooltipText()).toContain('Default 10, at most 1,440 on this deployment.');
            const closeAfter = inputNumber('Close after (hours)')!;
            expect(closeAfter.max()).toBe(720);
            expect(closeAfter.tooltipText()).toContain('Default 24, at most 720 on this deployment.');
        });

        it('keeps untouched durations out of the PATCH, even a stored one that is no whole number of minutes', () => {
            chatApi.updateBinding.mockReturnValue(of(binding({ name: 'Sales' })));
            const component = open(binding({ response_time_seconds: 90, close_after_seconds: 5400 }));
            expect(component.form.controls.response_time_minutes.value).toBe(2);
            expect(component.form.controls.close_after_hours.value).toBe(2);
            component.form.controls.name.setValue('Sales');
            component.submit();
            expect(chatApi.updateBinding).toHaveBeenCalledWith('b-1', { name: 'Sales' });
        });

        it('sends a typed duration in seconds, and a changed action and notice', () => {
            chatApi.updateBinding.mockReturnValue(of(binding({})));
            const component = open(binding({}));
            const controls = component.form.controls;
            controls.response_time_minutes.markAsDirty();
            controls.response_time_minutes.setValue(5);
            controls.close_after_hours.markAsDirty();
            controls.close_after_hours.setValue(48);
            controls.on_response_timeout.setValue('overdue');
            controls.handback_message.setValue('');
            component.submit();
            expect(chatApi.updateBinding).toHaveBeenCalledWith('b-1', {
                response_time_seconds: 300,
                close_after_seconds: 172_800,
                on_response_timeout: 'overdue',
                handback_message: '',
            });
        });

        it('shows the hand-back notice only for hand back', () => {
            const component = open(binding({}));
            showInactivity(component);
            const notice = (): Element | undefined =>
                Array.from((fixture.nativeElement as HTMLElement).querySelectorAll('app-textarea')).find((element) =>
                    element.textContent?.includes('Hand-back notice')
                );
            expect(notice()).toBeDefined();

            component.form.controls.on_response_timeout.setValue('overdue');
            fixture.detectChanges();
            expect(notice()).toBeUndefined();
        });

        it('shows close after as Never on Ongoing, out of the checks and the PATCH, and back on Support', () => {
            chatApi.updateBinding.mockReturnValue(of(binding({ style: 'ongoing' })));
            const component = open(binding({}));
            showInactivity(component);
            component.form.controls.style.setValue('ongoing');
            fixture.detectChanges();

            const never = inputNumber('Close after (hours)')!;
            expect(never.placeholder()).toBe('Never');
            expect(never.isDisabled()).toBe(true);
            expect(never.value()).toBeNull();
            expect(component.form.controls.close_after_hours.disabled).toBe(true);

            component.submit();
            expect(chatApi.updateBinding).toHaveBeenCalledWith('b-1', { style: 'ongoing' });

            component.form.controls.style.setValue('support');
            fixture.detectChanges();
            expect(component.form.controls.close_after_hours.enabled).toBe(true);
            expect(inputNumber('Close after (hours)')!.value()).toBe(24);
        });

        it('opens an Ongoing desk with close after as Never', () => {
            const component = open(binding({ style: 'ongoing', on_response_timeout: 'wait' }));
            expect(component.form.controls.close_after_hours.disabled).toBe(true);
            expect(component.isOngoing()).toBe(true);
        });

        it('warns that an Ongoing desk with Keep waiting can leave a visitor waiting for ever', () => {
            const component = open(binding({}));
            showInactivity(component);
            const hint = (): string => text('app-hint-message').join(' ');
            component.form.controls.on_response_timeout.setValue('wait');
            fixture.detectChanges();
            expect(hint()).toBe('');

            component.form.controls.style.setValue('ongoing');
            fixture.detectChanges();
            expect(hint()).toContain('they can wait for a person for ever');

            component.form.controls.on_response_timeout.setValue('handback');
            fixture.detectChanges();
            expect(hint()).toBe('');
        });

        it('leaves the notice out of a create while the limits failed to load, so the server default stands', () => {
            chatApi.getBindingLimits.mockReturnValue(throwError(() => new HttpErrorResponse({ status: 500 })));
            chatApi.createBinding.mockReturnValue(of({ ...binding({ id: 'b-2' }), identity_secret: null }));
            const component = open(null);
            component.form.patchValue({
                name: 'Portal',
                graph_id: 5,
                token_budget_per_conversation: 50_000,
                daily_token_budget: 1_000_000,
                response_time_minutes: 10,
                on_response_timeout: 'handback',
                close_after_hours: 24,
            });
            component.submit();
            const body = chatApi.createBinding.mock.calls[0][0];
            expect(body).not.toHaveProperty('handback_message');
            expect(body).toEqual(expect.objectContaining({ response_time_seconds: 600, close_after_seconds: 86_400 }));

            // Typed empty, it is sent empty: post nothing.
            component.form.controls.handback_message.setValue('');
            component.submit();
            expect(chatApi.createBinding.mock.calls[1][0]).toEqual(expect.objectContaining({ handback_message: '' }));
        });

        it("preselects the server's default style on a new desk, and the client's only when the limits failed", () => {
            chatApi.getBindingLimits.mockReturnValue(
                of({ ...LIMITS, defaults: { ...LIMITS.defaults, style: 'ongoing' } })
            );
            chatApi.createBinding.mockReturnValue(of({ ...binding({ id: 'b-2' }), identity_secret: null }));
            const component = open(null);
            expect(component.form.controls.style.value).toBe('ongoing');
            expect(component.form.controls.close_after_hours.disabled).toBe(true);
            component.form.patchValue({ name: 'Portal', graph_id: 5 });
            component.submit();
            expect(chatApi.createBinding).toHaveBeenCalledWith(expect.objectContaining({ style: 'ongoing' }));

            chatApi.getBindingLimits.mockReturnValue(throwError(() => new HttpErrorResponse({ status: 500 })));
            expect(open(null).form.controls.style.value).toBe('support');
        });

        it("keeps a style picked before the limits arrived, and an existing desk's own style", () => {
            const limits$ = new Subject<ChatBindingLimits>();
            chatApi.getBindingLimits.mockReturnValue(limits$);
            const component = open(null);
            fixture.detectChanges();
            radios()[1].click();
            limits$.next({ ...LIMITS, defaults: { ...LIMITS.defaults, style: 'support' } });
            expect(component.form.controls.style.value).toBe('ongoing');

            chatApi.getBindingLimits.mockReturnValue(
                of({ ...LIMITS, defaults: { ...LIMITS.defaults, style: 'ongoing' } })
            );
            expect(open(binding({})).form.controls.style.value).toBe('support');
        });

        describe('the warning about existing conversations', () => {
            /** The effects listed on the tab shown. */
            const shownEffects = (): string[] =>
                text('.bindings-dialog__tab:not([hidden]) .bindings-dialog__backlog li');

            /** Edits as the user would, then renders. */
            function edit(change: () => void): void {
                change();
                fixture.detectChanges();
            }

            /** As typing does: a duration control counts once dirty. */
            function type(control: FormControl<number | null>, units: number): void {
                control.markAsDirty();
                control.setValue(units);
            }

            it('says nothing on create, whatever the rules', () => {
                const component = open(null);
                edit(() => {
                    component.form.controls.style.setValue('ongoing');
                    component.form.controls.style.setValue('support');
                    type(component.form.controls.response_time_minutes, 1);
                    type(component.form.controls.close_after_hours, 1);
                });
                showInactivity(component);
                expect(component.backlogEffects()).toEqual([]);
                expect((fixture.nativeElement as HTMLElement).querySelector('.bindings-dialog__backlog')).toBeNull();
            });

            it('says nothing when no change acts on existing conversations', () => {
                const component = open(binding({}));
                const controls = component.form.controls;
                showInactivity(component);
                edit(() => {
                    controls.name.setValue('Sales');
                    type(controls.response_time_minutes, 20);
                    type(controls.close_after_hours, 48);
                    controls.handback_message.setValue('Back to the bot, sorry.');
                });
                expect(shownEffects()).toEqual([]);

                // A shorter response time that only marks overdue, or keeps waiting, reaches no visitor.
                edit(() => {
                    type(controls.response_time_minutes, 1);
                    controls.on_response_timeout.setValue('overdue');
                });
                expect(shownEffects()).toEqual([]);
                edit(() => controls.on_response_timeout.setValue('wait'));
                expect(shownEffects()).toEqual([]);
            });

            it('warns that switching to Support closes the conversations silent for longer, on General too', () => {
                const component = open(binding({ style: 'ongoing', on_response_timeout: 'wait' }));
                edit(() => component.form.controls.style.setValue('support'));
                expect(component.activeTab()).toBe('general');
                expect(shownEffects()).toEqual(['Conversations with no message for more than 24 hours close.']);
                expect(
                    (fixture.nativeElement as HTMLElement)
                        .querySelector('.bindings-dialog__backlog .hint-message')
                        ?.classList.contains('hint-message--warning')
                ).toBe(true);

                showInactivity(component);
                expect(shownEffects()).toEqual(['Conversations with no message for more than 24 hours close.']);
            });

            it('describes Save by the warning while it applies, so it is read before saving from any tab', () => {
                const host = (): HTMLElement => fixture.nativeElement as HTMLElement;
                const saveButton = (): HTMLButtonElement =>
                    Array.from(host().querySelectorAll<HTMLButtonElement>('.bindings-dialog__actions button')).find(
                        (button) => button.textContent?.trim() === 'Save'
                    )!;
                const component = open(binding({ style: 'ongoing', on_response_timeout: 'wait' }));
                expect(saveButton().hasAttribute('aria-describedby')).toBe(false);

                edit(() => component.form.controls.style.setValue('support'));
                // On General, where the switch was made; the copy it points at is the Inactivity tab's, hidden here.
                expect(component.activeTab()).toBe('general');
                const description = document.getElementById(saveButton().getAttribute('aria-describedby')!);
                expect(description?.textContent).toContain('Applies to this desk');
                expect(description?.textContent).toContain(
                    'Conversations with no message for more than 24 hours close.'
                );
                // One id only, though the warning shows on both tabs.
                expect(host().querySelectorAll(`[id="${description?.id}"]`)).toHaveLength(1);

                edit(() => component.form.controls.style.setValue('ongoing'));
                expect(saveButton().hasAttribute('aria-describedby')).toBe(false);
            });

            it('warns that a shorter close after closes the conversations silent for longer, on Inactivity only', () => {
                const component = open(binding({}));
                edit(() => type(component.form.controls.close_after_hours, 1));
                expect(shownEffects()).toEqual([]);
                showInactivity(component);
                expect(shownEffects()).toEqual(['Conversations with no message for more than 1 hour close.']);
            });

            it('warns that switching to hand back hands back the visitors who waited longer, with the notice if any', () => {
                const component = open(binding({ on_response_timeout: 'wait' }));
                showInactivity(component);
                edit(() => component.form.controls.on_response_timeout.setValue('handback'));
                expect(shownEffects()).toEqual([
                    'Visitors who have waited for a person for more than 10 minutes go back to the bot, including ' +
                        'ones an operator has taken over, with the hand-back notice.',
                ]);

                edit(() => component.form.controls.handback_message.setValue('  '));
                expect(shownEffects()).toEqual([
                    'Visitors who have waited for a person for more than 10 minutes go back to the bot, including ' +
                        'ones an operator has taken over.',
                ]);
            });

            it('warns that a shorter response time with hand back hands back more visitors, both effects listed', () => {
                const component = open(binding({ style: 'ongoing' }));
                showInactivity(component);
                edit(() => {
                    type(component.form.controls.response_time_minutes, 1);
                    component.form.controls.style.setValue('support');
                });
                expect(shownEffects()).toEqual([
                    'Conversations with no message for more than 24 hours close.',
                    'Visitors who have waited for a person for more than 1 minute go back to the bot, including ' +
                        'ones an operator has taken over, with the hand-back notice.',
                ]);
            });
        });

        it('opens the Inactivity tab on Save when a rule is invalid there', () => {
            const component = open(binding({}));
            component.form.controls.response_time_minutes.setValue(null);
            component.submit();
            expect(chatApi.updateBinding).not.toHaveBeenCalled();
            expect(component.activeTab()).toBe('inactivity');
        });

        it('blocks a typed duration above the deployment cap locally, in its unit', () => {
            const component = open(binding({}));
            showInactivity(component);
            component.form.controls.response_time_minutes.markAsDirty();
            component.form.controls.response_time_minutes.setValue(1441);
            fixture.detectChanges();
            expect(component.durationCapMessage('response_time_seconds')).toBe(
                'At most 1,440 minutes on this deployment'
            );
            expect(text('.input__message--error')).toEqual(['At most 1,440 minutes on this deployment']);
            component.submit();
            expect(chatApi.updateBinding).not.toHaveBeenCalled();
        });

        it('shows duration_above_cap on the refused duration, in its unit, on its tab', () => {
            chatApi.updateBinding.mockReturnValue(
                throwError(
                    () =>
                        new HttpErrorResponse({
                            status: 400,
                            error: {
                                code: 'duration_above_cap',
                                message: 'Above the cap.',
                                field: 'close_after_seconds',
                                max: 172_800,
                            },
                        })
                )
            );
            const component = open(binding({}));
            fixture.detectChanges();
            component.form.controls.close_after_hours.markAsDirty();
            component.form.controls.close_after_hours.setValue(72);
            component.submit();
            fixture.detectChanges();
            expect(component.durationCapMessage('close_after_seconds')).toBe('At most 48 hours on this deployment');
            expect(component.errorMessage()).toBeNull();
            expect(component.activeTab()).toBe('inactivity');
        });
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
    describe("the server's refusals of a name field", () => {
        const refused = (error: unknown) =>
            throwError(() => new HttpErrorResponse({ status: (error as { status: number }).status, error }));

        /** The error shown under the custom input labelled `label`, as the user sees it. */
        function fieldError(label: string): string | null {
            const host: HTMLElement = fixture.nativeElement;
            const input = Array.from(host.querySelectorAll('app-custom-input')).find(
                (candidate) => candidate.querySelector('label')?.textContent?.trim() === label
            );
            return input?.querySelector('.error-message')?.textContent?.trim() ?? null;
        }

        const announcement = (): string | undefined =>
            text('.bindings-dialog__form > [role="alert"]').find((message) => message !== '');

        /** Saves a renamed bot, which the server refuses with `body`. */
        function saveRefused(body: unknown): ChatBindingsDialogComponent {
            chatApi.updateBinding.mockReturnValue(refused(body));
            const component = open(binding({}));
            component.form.controls.bot_display_name.setValue('Mike');
            component.form.controls.operator_display_name.setValue('Helpers');
            component.submit();
            fixture.detectChanges();
            return component;
        }

        it('shows bot_name_taken under the bot name, says it, and stays open without a toast', () => {
            const message =
                'An operator on this desk already uses this name; visitors could not tell the bot from them. Choose another bot name.';
            const component = saveRefused({ status: 409, code: 'bot_name_taken', message, field: 'bot_display_name' });

            expect(fieldError('Displayed bot name')).toBe(message);
            expect(announcement()).toBe(`Displayed bot name: ${message}`);
            expect(component.errorMessage()).toBeNull();
            expect(component.activeTab()).toBe('general');
            expect(TestBed.inject(ToastService).error).not.toHaveBeenCalled();
            expect(TestBed.inject(DialogRef).close).not.toHaveBeenCalled();

            // Gone with the next edit of the field, and the save goes out again.
            component.form.controls.bot_display_name.setValue('Ava');
            fixture.detectChanges();
            expect(fieldError('Displayed bot name')).toBeNull();
            expect(component.form.valid).toBe(true);
        });

        it('shows refused characters and lengths on the fields the validation errors name, without the validator prefix', () => {
            const component = saveRefused({
                status: 400,
                code: 'validation_error',
                message: 'Validation failed for PATCH /chat/operator/v1/bindings/b-1',
                errors: [
                    {
                        message: 'Value error, Must be plain text: U+202E is not allowed.',
                        key: 'bot_display_name',
                        source: 'body',
                    },
                    { message: 'Value error, Must be at most 64 characters.', key: 'data.operator_display_name' },
                ],
            });

            expect(fieldError('Displayed bot name')).toBe('Must be plain text: U+202E is not allowed.');
            expect(component.textFieldError('operator_display_name')).toBe('Must be at most 64 characters.');
            expect(announcement()).toBe(
                'Displayed bot name: Must be plain text: U+202E is not allowed. ' +
                    'Displayed operator name: Must be at most 64 characters.'
            );
            // The first refused field's tab; the other refusal waits on its own tab.
            expect(component.activeTab()).toBe('general');
            component.activeTab.set('handoff');
            fixture.detectChanges();
            expect(fieldError('Displayed operator name')).toBe('Must be at most 64 characters.');
            expect(component.errorMessage()).toBeNull();
            expect(TestBed.inject(DialogRef).close).not.toHaveBeenCalled();
        });

        it('says validation errors that name no field of the dialog in the banner, beside the placed ones', () => {
            const component = saveRefused({
                status: 400,
                code: 'validation_error',
                message: 'Validation failed',
                errors: [
                    { message: 'Value error, Must be plain text: U+0007 is not allowed.', key: 'bot_display_name' },
                    { message: 'Input should be a valid list', key: 'allowed_origins' },
                ],
            });
            expect(component.textFieldError('bot_display_name')).toBe('Must be plain text: U+0007 is not allowed.');
            expect(component.errorMessage()).toBe('Input should be a valid list');
        });

        it('keeps the banner for a validation error that names no field', () => {
            const component = saveRefused({
                status: 400,
                code: 'validation_error',
                message: 'The body is nested too deeply.',
            });
            expect(component.errorMessage()).toBe('The body is nested too deeply.');
            expect(component.textFieldError('bot_display_name')).toBe('');
            expect(announcement()).toBeUndefined();
        });
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
        expect(text('.bindings-dialog__title')).toEqual(['New desk']);
        expect(text('.bindings-dialog__actions app-button')).not.toContain('Rotate key');

        open(binding({}));
        expect(text('.bindings-dialog__title')).toEqual(['Desk settings']);
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

        component.close();
        expect(TestBed.inject(DialogRef).close).toHaveBeenCalledWith(expect.objectContaining({ public_key: 'pk-2' }));
    });
});
