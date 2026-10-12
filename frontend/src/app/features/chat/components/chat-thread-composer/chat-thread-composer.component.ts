import { HttpErrorResponse } from '@angular/common/http';
import {
    Component,
    computed,
    DestroyRef,
    effect,
    inject,
    input,
    linkedSignal,
    output,
    signal,
    untracked,
    viewChild,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { FormControl, ReactiveFormsModule, Validators } from '@angular/forms';
import {
    ButtonComponent,
    CustomInputComponent,
    HintMessageComponent,
    JSON_EDITOR_OPTIONS,
    JsonEditorComponent,
    TabButtonComponent,
} from '@shared/components';
import { extractHttpErrorMessage } from '@shared/utils';

import { ToastService } from '../../../../services/notifications';
import {
    ChatConversation,
    ChatErrorBody,
    ChatOperatorMessage,
    ChatSendState,
    ChatVisitorMessageExtras,
} from '../../models/chat.model';
import { ChatApiService } from '../../services/chat-api.service';
import { ChatInboxStreamService } from '../../services/chat-inbox-stream.service';

export type ChatComposerRole = 'visitor' | 'operator';

/** The conversation is the one the reply was sent on, which the operator may have left by the time it lands. */
export interface ChatOperatorReplySent {
    conversationId: string;
    message: ChatOperatorMessage;
}

const SEND_STATE_NOTICES: Record<ChatSendState, string | null> = {
    processing: null,
    forwarded_to_operator: 'Forwarded to an operator: no run was started.',
    budget_exhausted: 'Budget exhausted: the binding answered with its fixed message or handed off.',
};

let nextComposerId = 0;

const EXTRA_DATA_ERROR = 'Extra data must be a JSON object, e.g. {"plan": "pro"}.';

/** The widget's `chat_extra_data`: empty is none; anything but a JSON object is refused before it is sent. */
function parseExtraData(text: string): { value: Record<string, unknown> | null; error: string | null } {
    if (!text.trim()) return { value: null, error: null };
    try {
        const parsed: unknown = JSON.parse(text);
        if (parsed && typeof parsed === 'object' && !Array.isArray(parsed)) {
            return { value: parsed as Record<string, unknown>, error: null };
        }
    } catch {
        // Falls through to the same error as a valid non-object.
    }
    return { value: null, error: EXTRA_DATA_ERROR };
}

const ROLES: { id: ChatComposerRole; label: string }[] = [
    { id: 'visitor', label: 'Visitor' },
    { id: 'operator', label: 'Operator' },
];

/**
 * The open thread's composer. Operators reply on the operator API once they hold the conversation. A test
 * conversation started on this page can also be written to as its visitor: sent on the public API with the visitor
 * token, exactly as the widget would, and locked while the bot replies. Replies arrive on the inbox stream.
 */
@Component({
    selector: 'app-chat-thread-composer',
    imports: [
        ReactiveFormsModule,
        ButtonComponent,
        CustomInputComponent,
        HintMessageComponent,
        TabButtonComponent,
        JsonEditorComponent,
    ],
    templateUrl: './chat-thread-composer.component.html',
    styleUrls: ['./chat-thread-composer.component.scss'],
})
export class ChatThreadComposerComponent {
    readonly conversation = input.required<ChatConversation>();
    // Issued only when a test conversation is created, so only tests started on this page can be written to as the visitor.
    readonly visitorToken = input<string | null>(null);
    // A token being fetched for an older test conversation, or why that failed.
    readonly visitorTokenPending = input(false);
    readonly visitorTokenError = input<string | null>(null);
    readonly isClaimedByMe = input(false);
    // A claim or release in flight on the page.
    readonly isActionPending = input(false);
    readonly claimRequested = output<void>();
    readonly operatorMessageSent = output<ChatOperatorReplySent>();

    private readonly inputField = viewChild.required(CustomInputComponent);

    readonly conversationId = computed(() => this.conversation().id);
    readonly isTest = computed(() => this.conversation().is_test);
    readonly canWriteAsVisitor = computed(() => this.isTest() && !!this.visitorToken());
    readonly visitorUnavailableReason = computed(() =>
        this.visitorTokenPending() ? 'Getting a visitor token…' : this.visitorTokenError()
    );
    // Back to the default whenever another conversation opens; a stream update of the same one keeps the choice.
    // A computed key, so an unchanged key does not reach the linked signal.
    private readonly roleKey = computed(() => `${this.conversationId()}:${this.canWriteAsVisitor()}`);
    readonly role = linkedSignal<string, ChatComposerRole>({
        source: this.roleKey,
        computation: () => (this.canWriteAsVisitor() ? 'visitor' : 'operator'),
    });
    // The conversation a send is in flight on: the lock belongs to it, not to whichever conversation is open.
    private readonly sendingOn = signal<string | null>(null);
    readonly isSending = computed(() => this.sendingOn() === this.conversationId());
    readonly notice = signal<string | null>(null);
    // A run the send just started, until the stream reports this conversation again.
    readonly isAwaitingRun = signal(false);
    readonly isProcessing = computed(() => this.conversation().state === 'processing' || this.isAwaitingRun());
    readonly isVisitor = computed(() => this.role() === 'visitor');
    readonly canSend = computed(() =>
        this.isVisitor()
            ? !this.isSending() && !this.isProcessing()
            : this.isClaimedByMe() && !this.isSending() && !this.isActionPending()
    );
    readonly isExtraDataOpen = signal(false);
    // The extra-data error waits for a blur or a send attempt, so it is not announced on every keystroke.
    readonly isExtraDataTouched = signal(false);
    readonly extraData = computed(() => parseExtraData(this.extraDataText()));
    // The message input stays usable while the JSON is wrong; only sending is blocked.
    readonly extraDataError = computed(() => (this.isExtraDataTouched() ? this.extraData().error : null));
    readonly canSubmit = computed(() => this.canSend() && !(this.isVisitor() && this.extraData().error));
    readonly placeholder = computed(() => {
        if (this.isVisitor())
            return this.isProcessing() ? 'Waiting for the reply…' : 'Message as the visitor, Enter to send';
        return this.isClaimedByMe() ? 'Reply as operator, Enter to send' : 'Claim the conversation to reply';
    });

    private readonly syncInput = effect(() => {
        if (this.canSend()) this.message.enable();
        else this.message.disable();
    });
    // Keyed on the id: a stream update of the open conversation must not wipe the draft or the notice.
    private readonly resetOnConversation = effect(() => {
        this.conversationId();
        untracked(() => {
            this.message.reset();
            this.extraDataText.set('');
            this.isExtraDataOpen.set(false);
            this.isExtraDataTouched.set(false);
            this.notice.set(null);
        });
    });
    // Any newer row means the stream spoke; a reconnect may have missed the idle (no replay). Either ends the wait.
    private readonly endWaitOnUpdate = effect(() => {
        this.conversation();
        this.chatInboxStream.readyEpoch();
        untracked(() => this.isAwaitingRun.set(false));
    });

    protected readonly roles = ROLES;
    private readonly composerId = nextComposerId++;
    protected readonly visitorUnavailableId = `chat-composer-visitor-unavailable-${this.composerId}`;
    protected readonly message = new FormControl('', { nonNullable: true, validators: [Validators.required] });
    protected readonly extraDataId = `chat-composer-extra-data-${this.composerId}`;
    protected readonly extraDataEditorOptions = {
        ...JSON_EDITOR_OPTIONS,
        lineNumbers: 'off' as const,
        ariaLabel: 'Extra data (JSON) sent with every visitor message',
    };
    // What the editor holds; parsed once here into the object to send (the editor itself only checks syntax).
    protected readonly extraDataText = signal('');

    private readonly chatApi = inject(ChatApiService);
    private readonly chatInboxStream = inject(ChatInboxStreamService);
    private readonly toastService = inject(ToastService);
    private readonly destroyRef = inject(DestroyRef);

    focus(): void {
        this.inputField().inputEl?.nativeElement.focus();
    }

    send(): void {
        if (this.isVisitor()) this.isExtraDataTouched.set(true);
        if (this.message.invalid || !this.canSubmit()) return;
        if (this.isVisitor()) this.sendAsVisitor();
        else this.sendAsOperator();
    }

    private sendAsVisitor(): void {
        const token = this.visitorToken();
        if (!token) return;
        // A response for a conversation the operator has since left must not touch the open one.
        const sentOn = this.conversation();
        this.sendingOn.set(sentOn.id);
        this.notice.set(null);
        this.chatApi
            .sendAsVisitor(sentOn.id, token, this.message.value, this.visitorExtras())
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe({
                next: (result) => {
                    this.endSend(sentOn.id);
                    if (this.conversationId() !== sentOn.id) return;
                    this.message.reset();
                    const streamSpoke = this.conversation() !== sentOn;
                    if (result.state === 'processing' && !streamSpoke) this.isAwaitingRun.set(true);
                    this.notice.set(SEND_STATE_NOTICES[result.state]);
                },
                error: (error: HttpErrorResponse) => {
                    this.endSend(sentOn.id);
                    if (this.conversationId() !== sentOn.id) return;
                    // Widget-side errors are shown inline, exactly as a widget would.
                    const body = error.error as ChatErrorBody | null;
                    // A refused field (extra data, action) is named in `errors`; the top-level message is generic.
                    const fieldError = body?.code === 'validation_error' ? body.errors?.[0]?.message : undefined;
                    this.notice.set(fieldError ?? body?.message ?? extractHttpErrorMessage(error));
                    const streamSpoke = this.conversation() !== sentOn;
                    if (body?.code === 'run_in_progress' && !streamSpoke) this.isAwaitingRun.set(true);
                },
            });
    }

    private sendAsOperator(): void {
        const sentOn = this.conversationId();
        this.sendingOn.set(sentOn);
        this.chatApi
            .reply(sentOn, this.message.value)
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe({
                next: (message) => {
                    this.endSend(sentOn);
                    // The draft on screen belongs to another conversation once the operator has switched.
                    if (this.conversationId() === sentOn) this.message.reset();
                    this.operatorMessageSent.emit({ conversationId: sentOn, message });
                },
                error: (error: HttpErrorResponse) => {
                    this.endSend(sentOn);
                    this.toastService.error(extractHttpErrorMessage(error));
                },
            });
    }

    // Sent with every visitor message while set; the server keeps the latest value for later runs.
    private visitorExtras(): ChatVisitorMessageExtras {
        const extraData = this.extraData().value;
        return extraData ? { chat_extra_data: extraData } : {};
    }

    private endSend(conversationId: string): void {
        if (this.sendingOn() === conversationId) this.sendingOn.set(null);
    }
}
