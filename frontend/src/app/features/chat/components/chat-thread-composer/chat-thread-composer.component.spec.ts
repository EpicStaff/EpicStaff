import { HttpErrorResponse } from '@angular/common/http';
import { CUSTOM_ELEMENTS_SCHEMA, signal } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { FormsModule } from '@angular/forms';
import { By } from '@angular/platform-browser';
import { JsonEditorComponent } from '@shared/components';
import { MonacoEditorModule } from 'ngx-monaco-editor-v2';
import { of, Subject, throwError } from 'rxjs';

import { ToastService } from '../../../../services/notifications';
import { ChatConversation, ChatOperatorMessage, ChatSendResult } from '../../models/chat.model';
import { ChatApiService } from '../../services/chat-api.service';
import { ChatInboxStreamService } from '../../services/chat-inbox-stream.service';
import { ChatThreadComposerComponent } from './chat-thread-composer.component';

class ResizeObserverStub {
    observe(): void {}
    unobserve(): void {}
    disconnect(): void {}
}

const row = (overrides: Partial<ChatConversation> = {}): ChatConversation => ({
    id: 'c-1',
    binding_id: 'b-1',
    mode: 'bot',
    state: 'idle',
    is_test: true,
    assigned_operator_id: null,
    tokens_used: 0,
    turns: 0,
    tokens_today: 0,
    turns_today: 0,
    last_message_at: null,
    last_message_preview: '',
    handoff_reason: '',
    handoff_at: null,
    ...overrides,
});

describe('ChatThreadComposerComponent', () => {
    let fixture: ComponentFixture<ChatThreadComposerComponent>;
    const readyEpoch = signal(0);
    const chatApi = { sendAsVisitor: vi.fn(), reply: vi.fn() };

    const host = (): HTMLElement => fixture.nativeElement;
    const input = (): HTMLInputElement => host().querySelector('input') as HTMLInputElement;
    const roleButtons = () => Array.from(host().querySelectorAll<HTMLButtonElement>('app-tab-button button'));
    const notice = (): string =>
        host().querySelector('[role="status"]')?.textContent?.replace(/\s+/g, ' ').trim() ?? '';

    function setInputs(inputs: Record<string, unknown>): void {
        Object.entries(inputs).forEach(([name, value]) => fixture.componentRef.setInput(name, value));
        fixture.detectChanges();
    }

    // The control, not the DOM: NgModel writes a value back into the input a microtask later.
    const draft = (): string => fixture.componentInstance['message'].value;

    function type(value: string): void {
        input().value = value;
        input().dispatchEvent(new Event('input'));
        fixture.detectChanges();
    }

    const sendButton = (): HTMLButtonElement =>
        Array.from(host().querySelectorAll<HTMLButtonElement>('.composer__row button')).find(
            (button) => button.textContent?.trim() === 'Send'
        ) as HTMLButtonElement;

    function openExtraData(): void {
        (host().querySelector('.composer__extra-toggle') as HTMLButtonElement).click();
        fixture.detectChanges();
    }

    /** Typing in the editor: Monaco does not run in jsdom, so its change output is emitted as the editor would. */
    function typeExtraData(value: string): void {
        const editor = fixture.debugElement.query(By.directive(JsonEditorComponent))
            .componentInstance as JsonEditorComponent;
        editor.onJsonChange(value);
        fixture.detectChanges();
    }

    function pressEnter(): void {
        host()
            .querySelector('app-custom-input')
            ?.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter' }));
        fixture.detectChanges();
    }

    beforeEach(() => {
        vi.stubGlobal('ResizeObserver', ResizeObserverStub);
        vi.clearAllMocks();
        TestBed.configureTestingModule({
            imports: [ChatThreadComposerComponent],
            providers: [
                { provide: ChatApiService, useValue: chatApi },
                { provide: ChatInboxStreamService, useValue: { readyEpoch } },
                { provide: ToastService, useValue: { error: vi.fn() } },
            ],
        });
        // Monaco does not run in jsdom: as in the editor's own spec, its host renders as an unknown element.
        TestBed.overrideComponent(JsonEditorComponent, {
            remove: { imports: [MonacoEditorModule, FormsModule] },
            add: { schemas: [CUSTOM_ELEMENTS_SCHEMA] },
        });
        fixture = TestBed.createComponent(ChatThreadComposerComponent);
    });

    afterEach(() => vi.unstubAllGlobals());

    it('defaults a test conversation started here to Visitor and sends on the public path', () => {
        chatApi.sendAsVisitor.mockReturnValue(of({ message_id: 'm-1', state: 'processing' }));
        setInputs({ conversation: row(), visitorToken: 'vt-1' });
        expect(
            roleButtons().map((button) => [button.textContent?.trim(), button.getAttribute('aria-pressed')])
        ).toEqual([
            ['Visitor', 'true'],
            ['Operator', 'false'],
        ]);
        type('hello');
        pressEnter();
        expect(chatApi.sendAsVisitor).toHaveBeenCalledWith('c-1', 'vt-1', 'hello', {});
        expect(chatApi.reply).not.toHaveBeenCalled();
    });

    it('sends as the operator on the operator path once claimed, and offers Claim before that', () => {
        const sent = { id: 'm-2', role: 'operator', content: 'hi' } as ChatOperatorMessage;
        chatApi.reply.mockReturnValue(of(sent));
        const claimRequested = vi.fn();
        const operatorMessageSent = vi.fn();
        fixture.componentInstance.claimRequested.subscribe(claimRequested);
        fixture.componentInstance.operatorMessageSent.subscribe(operatorMessageSent);
        setInputs({ conversation: row(), visitorToken: 'vt-1' });

        roleButtons()[1].click();
        fixture.detectChanges();
        expect(input().disabled).toBe(true);
        const claim = host().querySelector('.composer__row app-button button') as HTMLButtonElement;
        expect(claim.textContent?.trim()).toBe('Claim to reply');
        claim.click();
        expect(claimRequested).toHaveBeenCalledTimes(1);

        setInputs({ conversation: row({ mode: 'human', assigned_operator_id: 3 }), isClaimedByMe: true });
        expect(fixture.componentInstance.role()).toBe('operator');
        type('hi');
        pressEnter();
        expect(chatApi.reply).toHaveBeenCalledWith('c-1', 'hi');
        expect(chatApi.sendAsVisitor).not.toHaveBeenCalled();
        expect(operatorMessageSent).toHaveBeenCalledWith({ conversationId: 'c-1', message: sent });
    });

    it('locks the visitor input while the bot replies and until the stream reports the conversation again', () => {
        chatApi.sendAsVisitor.mockReturnValue(of({ message_id: 'm-1', state: 'processing' } as ChatSendResult));
        setInputs({ conversation: row(), visitorToken: 'vt-1' });
        type('hello');
        pressEnter();
        expect(input().disabled).toBe(true);
        expect(notice()).toBe('Bot is replying…');

        setInputs({ conversation: row({ state: 'processing' }) });
        expect(input().disabled).toBe(true);

        setInputs({ conversation: row({ state: 'idle' }) });
        expect(input().disabled).toBe(false);
        expect(notice()).toBe('');
    });

    it('shows a 409 as a notice in the live region and keeps the lock', () => {
        chatApi.sendAsVisitor.mockReturnValue(
            throwError(
                () =>
                    new HttpErrorResponse({
                        status: 409,
                        error: { code: 'run_in_progress', message: 'A reply is still being written.' },
                    })
            )
        );
        setInputs({ conversation: row(), visitorToken: 'vt-1' });
        type('hello');
        pressEnter();
        expect(notice()).toContain('A reply is still being written.');
        expect(input().disabled).toBe(true);
        expect(host().querySelector('[role="status"]')?.getAttribute('aria-live')).toBe('polite');
    });

    it('reports a budget-exhausted send and drops the lock on a reconnect', () => {
        const response$ = new Subject<ChatSendResult>();
        chatApi.sendAsVisitor.mockReturnValue(response$);
        setInputs({ conversation: row(), visitorToken: 'vt-1' });
        type('hello');
        pressEnter();
        response$.next({ message_id: 'm-1', state: 'budget_exhausted' });
        fixture.detectChanges();
        expect(notice()).toBe('Budget exhausted: the binding answered with its fixed message or handed off.');

        chatApi.sendAsVisitor.mockReturnValue(of({ message_id: 'm-2', state: 'processing' }));
        type('again');
        pressEnter();
        expect(input().disabled).toBe(true);
        readyEpoch.update((value) => value + 1);
        fixture.detectChanges();
        expect(input().disabled).toBe(false);
    });

    it('lands an operator reply in the conversation it was sent on and keeps the next draft after a switch', () => {
        const reply$ = new Subject<ChatOperatorMessage>();
        chatApi.reply.mockReturnValue(reply$);
        const operatorMessageSent = vi.fn();
        fixture.componentInstance.operatorMessageSent.subscribe(operatorMessageSent);
        const claimed = { mode: 'human' as const, assigned_operator_id: 3, is_test: false };
        setInputs({ conversation: row({ id: 'c-a', ...claimed }), isClaimedByMe: true });
        type('for A');
        pressEnter();

        setInputs({ conversation: row({ id: 'c-b', ...claimed }) });
        expect(draft()).toBe('');
        expect(input().disabled).toBe(false);
        type('draft for B');

        const sent = { id: 'm-a', role: 'operator', content: 'for A' } as ChatOperatorMessage;
        reply$.next(sent);
        fixture.detectChanges();
        expect(operatorMessageSent).toHaveBeenCalledWith({ conversationId: 'c-a', message: sent });
        expect(draft()).toBe('draft for B');
    });

    it('keeps the draft and the notice through a stream update of the open conversation', () => {
        chatApi.sendAsVisitor.mockReturnValue(of({ message_id: 'm-1', state: 'forwarded_to_operator' }));
        setInputs({ conversation: row(), visitorToken: 'vt-1' });
        type('hello');
        pressEnter();
        expect(notice()).toBe('Forwarded to an operator: no run was started.');
        type('next');

        setInputs({ conversation: row({ mode: 'awaiting_human' }) });
        expect(draft()).toBe('next');
        expect(notice()).toBe('Forwarded to an operator: no run was started.');
    });

    it('keeps Visitor disabled while its token is fetched, then links it to why it failed', () => {
        setInputs({ conversation: row(), visitorToken: null, visitorTokenPending: true });
        expect(roleButtons()[0].disabled).toBe(true);
        let describedBy = roleButtons()[0].getAttribute('aria-describedby') as string;
        expect(host().querySelector(`#${describedBy}`)?.textContent?.trim()).toBe('Getting a visitor token…');

        setInputs({ visitorTokenPending: false, visitorTokenError: "Couldn't get a visitor token." });
        describedBy = roleButtons()[0].getAttribute('aria-describedby') as string;
        expect(host().querySelector(`#${describedBy}`)?.textContent?.trim()).toBe("Couldn't get a visitor token.");
        expect(roleButtons()[1].hasAttribute('aria-describedby')).toBe(false);

        setInputs({ visitorTokenError: null, visitorToken: 'vt-1' });
        expect(roleButtons()[0].disabled).toBe(false);
        expect(host().querySelector('.composer__caption')).toBeNull();
        expect(fixture.componentInstance.role()).toBe('visitor');
    });

    it('sends a JSON object of extra data with every visitor message', () => {
        chatApi.sendAsVisitor.mockReturnValue(of({ message_id: 'm-1', state: 'forwarded_to_operator' }));
        setInputs({ conversation: row(), visitorToken: 'vt-1' });
        openExtraData();
        typeExtraData('{"plan": "pro"}');
        type('hello');
        pressEnter();
        expect(chatApi.sendAsVisitor).toHaveBeenCalledWith('c-1', 'vt-1', 'hello', {
            chat_extra_data: { plan: 'pro' },
        });
        expect(host().querySelector('.composer__extra-error')).toBeNull();
    });

    it.each(['[1, 2]', '"text"', '{not json', 'null'])(
        'refuses extra data that is not a JSON object (%s) and sends nothing',
        (value) => {
            setInputs({ conversation: row(), visitorToken: 'vt-1' });
            openExtraData();
            typeExtraData(value);
            type('hello');
            pressEnter();
            expect(chatApi.sendAsVisitor).not.toHaveBeenCalled();
            expect(host().querySelector('.composer__extra-error')?.textContent).toContain('must be a JSON object');
            expect(sendButton().disabled).toBe(true);
            expect(input().disabled).toBe(false);
        }
    );

    it('offers extra data only when writing as the visitor', () => {
        setInputs({ conversation: row(), visitorToken: 'vt-1' });
        expect(host().querySelector('.composer__extra-toggle')).not.toBeNull();
        roleButtons()[1].click();
        fixture.detectChanges();
        expect(host().querySelector('.composer__extra')).toBeNull();

        setInputs({ conversation: row({ id: 'c-2', is_test: false }) });
        expect(host().querySelector('.composer__extra')).toBeNull();
    });

    it('names the refused field of a 400 validation_error instead of the generic message', () => {
        chatApi.sendAsVisitor.mockReturnValue(
            throwError(
                () =>
                    new HttpErrorResponse({
                        status: 400,
                        error: {
                            code: 'validation_error',
                            message: 'Validation failed for POST /messages',
                            errors: [{ message: 'chat_extra_data is larger than 8192 bytes' }],
                        },
                    })
            )
        );
        setInputs({ conversation: row(), visitorToken: 'vt-1' });
        type('hello');
        pressEnter();
        expect(notice()).toBe('chat_extra_data is larger than 8192 bytes');
    });

    it('shows the extra-data error only after leaving the field or trying to send', () => {
        setInputs({ conversation: row(), visitorToken: 'vt-1' });
        openExtraData();
        typeExtraData('[1]');
        expect(host().querySelector('.composer__extra-error')).toBeNull();
        expect(sendButton().disabled).toBe(true);

        host()
            .querySelector('.composer__extra app-json-editor')
            ?.dispatchEvent(new FocusEvent('focusout', { bubbles: true }));
        fixture.detectChanges();
        expect(host().querySelector('.composer__extra-error')?.getAttribute('role')).toBe('alert');
    });

    it('collapses and clears extra data when another conversation opens, and says how to clear the stored value', () => {
        setInputs({ conversation: row(), visitorToken: 'vt-1' });
        openExtraData();
        typeExtraData('{"plan": "pro"}');
        expect(host().querySelector('.composer__extra-hint')?.textContent?.trim()).toBe(
            'Leave empty to keep the last value; send {} to clear.'
        );

        setInputs({ conversation: row({ id: 'c-2' }) });
        expect(fixture.componentInstance.isExtraDataOpen()).toBe(false);
        expect(fixture.componentInstance.extraData().value).toBeNull();
        expect(host().querySelector('app-json-editor')).toBeNull();
    });

    it('edits extra data in the shared JSON editor, which starts empty, not as {}', () => {
        setInputs({ conversation: row(), visitorToken: 'vt-1' });
        openExtraData();
        const editor = fixture.debugElement.query(By.directive(JsonEditorComponent))
            .componentInstance as JsonEditorComponent;
        expect(editor.jsonData).toBe('');
        expect(editor.allowEmpty()).toBe(true);
        expect(editor.editorOptions.ariaLabel).toBe('Extra data (JSON) sent with every visitor message');
        expect(editor.resizable).toBe(false);

        // Collapsing keeps what was typed: it is still sent, and shown again on reopening.
        typeExtraData('{"plan": "pro"}');
        openExtraData();
        expect(host().querySelector('app-json-editor')).toBeNull();
        openExtraData();
        expect(
            (fixture.debugElement.query(By.directive(JsonEditorComponent)).componentInstance as JsonEditorComponent)
                .jsonData
        ).toBe('{"plan": "pro"}');
    });

    it('offers Claim to reply, or Take over once handed to a human, on a real conversation the operator does not hold', () => {
        const claimRequested = vi.fn();
        fixture.componentInstance.claimRequested.subscribe(claimRequested);
        const action = () => host().querySelector('.composer__row app-button button') as HTMLButtonElement;
        setInputs({ conversation: row({ is_test: false, mode: 'awaiting_human' }) });
        expect(action().textContent?.trim()).toBe('Claim to reply');
        action().click();
        expect(claimRequested).toHaveBeenCalledTimes(1);

        setInputs({ conversation: row({ is_test: false, mode: 'human', assigned_operator_id: 7 }) });
        expect(action().textContent?.trim()).toBe('Take over');

        setInputs({
            conversation: row({ is_test: false, mode: 'human', assigned_operator_id: 3 }),
            isClaimedByMe: true,
        });
        expect(action().textContent?.trim()).toBe('Send');
        expect(input().disabled).toBe(false);
    });

    it('shows Bot is replying… on a real conversation while a run is in progress', () => {
        setInputs({ conversation: row({ is_test: false, state: 'processing' }) });
        expect(notice()).toBe('Bot is replying…');
    });

    it('has no switch on a real conversation, and Visitor is unavailable while a test has no token', () => {
        setInputs({ conversation: row({ is_test: false }) });
        expect(roleButtons()).toEqual([]);
        expect(input().placeholder).toBe('Claim the conversation to reply');

        setInputs({ conversation: row({ id: 'c-2' }), visitorToken: null });
        expect(roleButtons()[0].disabled).toBe(true);
        expect(fixture.componentInstance.role()).toBe('operator');
    });
});
