import {
    Component,
    computed,
    DestroyRef,
    ElementRef,
    inject,
    input,
    linkedSignal,
    output,
    viewChild,
} from '@angular/core';
import { MatTooltipModule } from '@angular/material/tooltip';
import { AppSvgIconComponent, ButtonComponent } from '@shared/components';
import { TooltipOnOverflowDirective } from '@shared/directives';
import { ActionCode, ResourceCode } from '@shared/models';
import { copyWithFeedback } from '@shared/utils';

import { PhoneLayoutService } from '../../../../core/services/phone-layout.service';
import { PermissionsService } from '../../../../services/auth/permissions.service';
import { ProfileService } from '../../../../services/auth/profile.service';
import { ToastService } from '../../../../services/notifications';
import { CHAT_MODE_LABELS, ChatBinding, ChatConversation, ChatMode } from '../../models/chat.model';
import { ChatConversationActionsService } from '../../services/chat-conversation-actions.service';
import { OpenConversationService } from '../../services/open-conversation.service';
import {
    ConversationAction,
    ConversationActionContext,
    conversationHolder,
    conversationMenuItems,
    primaryConversationAction,
} from '../../utils/conversation-actions.util';
import { isClosed } from '../../utils/conversation-close.util';
import { deskRulesOf, operatorName, visitorName, waitDuration } from '../../utils/conversation-row.util';
import { isWaitingForPerson, isWaitOverdue, WAIT_OVERDUE_NOTE, WAIT_TICK_MS } from '../../utils/conversation-wait.util';
import { tickingNow } from '../../utils/ticking-now.util';
import { ChatActionMenuComponent, ChatActionMenuItem } from '../chat-action-menu/chat-action-menu.component';
import { ChatUsageRingComponent } from '../chat-usage-ring/chat-usage-ring.component';
import { ConversationAvatarComponent } from '../conversation-avatar/conversation-avatar.component';

/**
 * The ⋯ menu's actions: the conversation's own, Copy Visitor ID (the header's own, as it changes nothing), and Delete
 * Conversation, which the page carries out.
 */
type ThreadMenuAction = ConversationAction | 'copy-visitor-id' | 'delete';

// How long the copy icon shows its check after the conversation id was copied.
const ID_COPIED_CONFIRMATION_MS = 2000;

/** The wait chip after the visitor's name: how long they have waited, and whether past the desk's response time. */
interface ThreadWait {
    duration: string;
    isOverdue: boolean;
}

/**
 * The open conversation's header. On desktop one row: the visitor's avatar; their name, then how long they have waited
 * for a person (while they do, as the list's row says it), over the conversation's path (Bot, or Bot / Human with an
 * operator) and its id, which copies; then the Test chip; at the end the main action, today's usage against
 * its desk's limits and the ⋯ menu. On phones it is also the thread screen's nav bar: Back to the list, the visitor and
 * the ⋯ menu, with the mode (or Closed), Test chip and usage centred under it, then the handoff reason.
 */
@Component({
    selector: 'app-chat-thread-header',
    imports: [
        MatTooltipModule,
        TooltipOnOverflowDirective,
        AppSvgIconComponent,
        ButtonComponent,
        ChatActionMenuComponent,
        ChatUsageRingComponent,
        ConversationAvatarComponent,
    ],
    templateUrl: './chat-thread-header.component.html',
    styleUrl: './chat-thread-header.component.scss',
    host: {
        '[class.chat-thread-header--phone]': 'isPhone()',
    },
})
export class ChatThreadHeaderComponent {
    readonly conversation = input.required<ChatConversation>();
    /** The conversation's desk, which words its actions and sets its limits; null while that desk is not known. */
    readonly binding = input<ChatBinding | null>(null);
    /** The list the phone's Back returns to: the desk name or All desks; empty while not known. */
    readonly listTitle = input('');
    readonly isAllBindings = input(false);
    /** Offers Delete Conversation at the end of the ⋯ menu; the page decides when, and what it deletes. */
    readonly canDelete = input(false);
    readonly deleteRequested = output<void>();

    private readonly threadBack = viewChild<ElementRef<HTMLButtonElement>>('threadBack');

    readonly canUse = computed(() => this.permissionsService.can(ResourceCode.Chats, ActionCode.Use));
    readonly isClosed = computed(() => isClosed(this.conversation()));
    /** The thread's Back on phones, named after the list it returns to. */
    readonly backText = computed(() => this.listTitle() || 'Back');
    readonly backLabel = computed(() => {
        const title = this.listTitle();
        return title ? `Back to ${title}` : 'Back';
    });
    // Who holds the open conversation, for the phone's mode pill tooltip: "you", their name or "Operator #7"; null
    // while nobody does, and once it is closed.
    readonly holderLabel = computed(() => {
        const conversation = this.conversation();
        const operatorId = conversation.assigned_operator_id ?? null;
        if (operatorId === null || isClosed(conversation)) return null;
        if (operatorId === this.profileService.currentUserSignal()?.id) return 'you';
        return operatorName(operatorId, conversation.assigned_operator_name ?? null);
    });
    /**
     * Why the visitor was handed to a person, while that still matters: not back with the bot, not closed. A line under
     * the row on phones; in the wait chip's tooltip on desktop.
     */
    readonly handoffReason = computed(() => {
        const conversation = this.conversation();
        if (!conversation.handoff_reason || conversation.mode === 'bot' || isClosed(conversation)) return null;
        return conversation.handoff_reason;
    });
    /**
     * Desktop: how long the visitor has waited for a person, by the list row's rules; null while they do not. Only a
     * waiting conversation reads the seconds clock, so the header does not redraw every second for nothing.
     */
    readonly wait = computed((): ThreadWait | null => {
        const conversation = this.conversation();
        if (this.isPhone() || !isWaitingForPerson(conversation)) return null;
        const now = this.waitNow();
        const binding = this.binding();
        const overdueAfterMs = binding ? deskRulesOf(binding).overdueAfterMs : null;
        return {
            duration: waitDuration(conversation.visitor_waiting_since, now),
            isOverdue: isWaitOverdue(conversation, overdueAfterMs, now),
        };
    });
    /** The wait chip's tooltip: the overdue note, then the handoff reason; empty when there is neither. */
    readonly waitTooltip = computed(() =>
        [this.wait()?.isOverdue ? WAIT_OVERDUE_NOTE : null, this.handoffReason()]
            .filter((part) => part !== null)
            .join(' · ')
    );
    /**
     * Whether the conversation is in an operator's hands (Human mode), so its path reads Bot / Human. A close keeps the
     * mode, so a conversation closed while with an operator still says so; one awaiting a person is still Bot.
     */
    readonly isWithOperator = computed(() => this.conversation().mode === 'human');
    /** The check after the id was copied; back to the copy icon for another conversation. */
    readonly isIdCopied = linkedSignal({ source: () => this.conversation().id, computation: () => false });
    /** What the conversation's actions depend on. */
    private readonly actionContext = computed(
        (): ConversationActionContext => ({
            style: this.binding()?.style ?? null,
            holder: conversationHolder(this.conversation(), this.profileService.currentUserSignal()?.id ?? null),
            isClosed: this.isClosed(),
            isPhone: this.isPhone(),
            canUse: this.canUse(),
            isPending: this.isActionPending(),
        })
    );
    /** The main action, a button before the usage (see `primaryConversationAction`): on Support, for any holder. */
    readonly primaryAction = computed(() => primaryConversationAction(this.actionContext()));
    /**
     * The ⋯ menu: the conversation's other actions (see `conversationMenuItems`), then Copy Visitor ID, then Delete
     * Conversation, set apart. Copy Visitor ID is there on any conversation, open or closed, and needs no chats use: it
     * changes nothing. So the menu is never empty.
     */
    readonly conversationMenuItems = computed((): ChatActionMenuItem<ThreadMenuAction>[] => [
        ...conversationMenuItems(this.actionContext()),
        { id: 'copy-visitor-id', label: 'Copy Visitor ID' },
        ...(this.canDelete() ? [{ id: 'delete' as const, label: 'Delete Conversation', separated: true }] : []),
    ]);

    protected readonly isActionPending = inject(ChatConversationActionsService).isPending;
    protected readonly isPhone = inject(PhoneLayoutService).isPhone;
    protected readonly openConversation = inject(OpenConversationService);
    protected readonly visitorName = visitorName;

    private readonly conversationActions = inject(ChatConversationActionsService);
    private readonly permissionsService = inject(PermissionsService);
    private readonly profileService = inject(ProfileService);
    private readonly toastService = inject(ToastService);
    private readonly destroyRef = inject(DestroyRef);
    // The same period as the list's wait clock (a separate interval), so the header counts the seconds as the row does.
    private readonly waitNow = tickingNow(WAIT_TICK_MS);
    private idCopiedTimer: ReturnType<typeof setTimeout> | undefined;

    constructor() {
        this.destroyRef.onDestroy(() => clearTimeout(this.idCopiedTimer));
    }

    /** Copies the full conversation id, then shows the check for a moment where the copy icon was. */
    copyConversationId(): void {
        const conversationId = this.conversation().id;
        void copyWithFeedback(conversationId, this.toastService, 'Conversation ID copied').then((copied) => {
            // The header may be gone, or show another conversation, by now: the check is for the id that was copied.
            if (!copied || this.destroyRef.destroyed || this.conversation().id !== conversationId) return;
            this.isIdCopied.set(true);
            clearTimeout(this.idCopiedTimer);
            this.idCopiedTimer = setTimeout(() => this.isIdCopied.set(false), ID_COPIED_CONFIRMATION_MS);
        });
    }

    runConversationAction(action: ThreadMenuAction): void {
        const conversation = this.conversation();
        const run: Record<ThreadMenuAction, () => void> = {
            'take-over': () => this.conversationActions.takeOver(conversation),
            release: () => this.conversationActions.release(conversation),
            resolve: () => this.conversationActions.resolve(conversation),
            close: () => this.conversationActions.closeConversation(conversation),
            'copy-visitor-id': () => this.copyVisitorId(),
            delete: () => this.deleteRequested.emit(),
        };
        run[action]();
    }

    /** Phones: the thread screen's Back, where the focus goes as the thread pushes in. */
    focusBack(): void {
        // Without scrolling: a pane still sliding in may be past the edge, and the browser would scroll to it.
        this.threadBack()?.nativeElement.focus({ preventScroll: true });
    }

    protected modeLabel(mode: ChatMode): string {
        return CHAT_MODE_LABELS[mode];
    }

    /** A signed visitor's id from the desk's backend, else their visitor number on this desk. */
    private copyVisitorId(): void {
        const { chat_user_id: chatUserId, visitor_number: visitorNumber } = this.conversation();
        void copyWithFeedback(chatUserId || String(visitorNumber), this.toastService, 'Visitor ID copied');
    }
}
