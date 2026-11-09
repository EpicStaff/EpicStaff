import {
    Component,
    computed,
    ElementRef,
    inject,
    input,
    linkedSignal,
    LOCALE_ID,
    output,
    viewChild,
} from '@angular/core';
import { MatTooltipModule } from '@angular/material/tooltip';
import { AppSvgIconComponent, ButtonComponent } from '@shared/components';

import { ProfileService } from '../../../../services/auth/profile.service';
import { ChatConversation } from '../../models/chat.model';
import { ConversationReadMarksService } from '../../services/conversation-read-marks.service';
import { closeReasonLabel, closeReasonWord, isClosed } from '../../utils/conversation-close.util';
import {
    ConversationDeskRules,
    conversationTime,
    conversationTimeLabel,
    operatorName,
    senderPrefix,
    visitorName,
    waitDuration,
} from '../../utils/conversation-row.util';
import { isWaitingForPerson, isWaitOverdue, WAIT_OVERDUE_NOTE } from '../../utils/conversation-wait.util';
import { ConversationAvatarComponent } from '../conversation-avatar/conversation-avatar.component';

export type ConversationRowMove = 'next' | 'previous' | 'first' | 'last';

const ROW_MOVES: Record<string, ConversationRowMove> = {
    ArrowDown: 'next',
    ArrowUp: 'previous',
    Home: 'first',
    End: 'last',
};

interface ConversationHolder {
    /** Only the current user's is known; anyone else's badge shows a person icon. */
    avatarUrl: string | null;
    /** "you", their name, or "Operator #7". */
    label: string;
}

/**
 * One conversation in the list, as chat apps draw it: the visitor's avatar, name and last activity, then the last
 * message after who wrote it ("Bot is replying…" while a run is in flight). A taken one has its operator's badge on the
 * avatar's corner. A conversation where the visitor waits for a person has a bold name and, on its right, how long they
 * have waited and Take over (unless the current user holds it); the wait gets an alert icon and the error colour once
 * overdue. In progress, one with news the user has not opened has a green dot by its time and a brighter preview. A
 * closed one says why and when it closed.
 */
@Component({
    selector: 'app-conversation-row',
    imports: [MatTooltipModule, AppSvgIconComponent, ButtonComponent, ConversationAvatarComponent],
    templateUrl: './conversation-row.component.html',
    styleUrl: './conversation-row.component.scss',
})
export class ConversationRowComponent {
    readonly conversation = input.required<ChatConversation>();
    /** The current time, ticking, for the relative time. */
    readonly now = input.required<number>();
    /** Shown under the visitor's name on All desks; null on a desk's own list. */
    readonly deskName = input<string | null>(null);
    /** The desk's rules; null while the desk is not known: nobody is overdue, and a close is worded neutrally. */
    readonly rules = input<ConversationDeskRules | null>(null);
    readonly isSelected = input(false);
    /** The one row of the list that Tab reaches; the arrow keys move between rows. */
    readonly isTabStop = input(false);
    /** The current user may take conversations over (chats use). */
    readonly canTakeOver = input(false);
    readonly isActionPending = input(false);
    /** The row's section marks news the user has not opened (In progress): a dot and a brighter preview. */
    readonly marksUnread = input(false);
    readonly selectRequested = output<void>();
    readonly takeOverRequested = output<void>();
    readonly moveRequested = output<ConversationRowMove>();

    private readonly selectButton = viewChild.required<ElementRef<HTMLButtonElement>>('selectButton');

    private readonly myUserId = computed(() => this.profileService.currentUserSignal()?.id ?? null);
    protected readonly isUnread = computed(() => this.marksUnread() && this.readMarks.isUnread(this.conversation()));
    protected readonly name = computed(() => visitorName(this.conversation()));
    /** A signed visitor's id can be long: the full value is in a tooltip. */
    protected readonly isSigned = computed(() => !!this.conversation().chat_user_id);
    protected readonly isClosed = computed(() => isClosed(this.conversation()));
    /**
     * A closed row's time is its close, as Closed sorts by it; any other row's, its last message. A closed test stays
     * in Bot Testing, which sorts by the last message, so it keeps that time too.
     */
    private readonly isTimedByClose = computed(() => this.isClosed() && !this.conversation().is_test);
    private readonly shownTime = computed(() => {
        const conversation = this.conversation();
        return this.isTimedByClose() ? conversation.closed_at : conversation.last_message_at;
    });
    protected readonly time = computed(() => conversationTime(this.shownTime(), this.now(), this.locale));
    /** Waiting for a person (see `isWaitingForPerson`). */
    protected readonly isWaiting = computed(() => isWaitingForPerson(this.conversation()));
    protected readonly waitedFor = computed(() => waitDuration(this.conversation().visitor_waiting_since, this.now()));
    /** Waited past the desk's response time on a desk that marks it; moves with the clock. Tests run no timers. */
    protected readonly isOverdue = computed(() =>
        isWaitOverdue(this.conversation(), this.rules()?.overdueAfterMs ?? null, this.now())
    );
    protected readonly isReplying = computed(() => !this.isClosed() && this.conversation().state === 'processing');
    protected readonly preview = computed(() =>
        this.isReplying() ? 'Bot is replying…' : this.conversation().last_message_preview || 'No messages yet'
    );
    protected readonly sender = computed(() =>
        this.isReplying() ? null : senderPrefix(this.conversation(), this.myUserId())
    );
    protected readonly isSystemNote = computed(
        () => !this.isReplying() && this.conversation().last_message_role === 'system'
    );
    /** Nobody is on a closed conversation, so it shows no holder. */
    protected readonly holder = computed((): ConversationHolder | null => {
        const { assigned_operator_id: operatorId, assigned_operator_name: operatorDisplayName } = this.conversation();
        if (operatorId === null || this.isClosed()) return null;
        const me = this.profileService.currentUserSignal();
        if (me?.id === operatorId) return { avatarUrl: me.avatar_url, label: 'you' };
        return { avatarUrl: null, label: operatorName(operatorId, operatorDisplayName) };
    });
    // Resets on every new URL, so a fresh link (an expired signed one renewed) gets a fresh try.
    protected readonly holderImageFailed = linkedSignal({
        source: () => this.holder()?.avatarUrl ?? null,
        computation: () => false,
    });
    /** The badge is too small for initials: the holder's picture, or else a person icon. */
    protected readonly holderImageUrl = computed(() =>
        this.holderImageFailed() ? null : (this.holder()?.avatarUrl ?? null)
    );
    /** Why it closed, in a word ("Resolved"), with the full reason ("Resolved by Mike") as its tooltip. */
    protected readonly closeWord = computed(() =>
        this.isClosed() ? closeReasonWord(this.conversation().close_reason, this.rules()?.style ?? null) : ''
    );
    protected readonly closeReason = computed(() =>
        this.isClosed() ? closeReasonLabel(this.conversation(), this.rules()?.style ?? null, this.myUserId()) : ''
    );
    /** Not for a conversation the current user holds; one another operator holds asks before it is taken from them. */
    protected readonly offersTakeOver = computed(
        () => this.isWaiting() && this.canTakeOver() && this.conversation().assigned_operator_id !== this.myUserId()
    );
    /**
     * Visitor, desk (All desks only), last activity in words (the close, on a row timed by it), and what the
     * conversation needs. Times are absolute ("today at 2:05 PM"): relative ones would change the focused row's name
     * every minute, and be read out again.
     */
    protected readonly accessibleName = computed(() => {
        const conversation = this.conversation();
        const timeLabel = conversationTimeLabel(this.shownTime(), this.now(), this.locale);
        const waitingSince = this.isWaiting()
            ? conversationTimeLabel(conversation.visitor_waiting_since, this.now(), this.locale)
            : '';
        const holder = this.holder();
        const closeReason = this.closeReason();
        return [
            this.name(),
            this.deskName(),
            timeLabel ? `${this.isTimedByClose() ? 'closed' : 'last message'} ${timeLabel}` : null,
            conversation.is_test ? 'test' : null,
            closeReason ? lowerFirst(closeReason) : null,
            waitingSince ? `waiting for a person since ${waitingSince}` : null,
            this.isOverdue() ? 'overdue' : null,
            holder ? `taken by ${holder.label}` : null,
            this.isReplying() ? 'bot is replying' : null,
            this.isUnread() ? 'unread' : null,
        ]
            .filter(Boolean)
            .join(', ');
    });
    protected readonly previewId = computed(() => `conversation-preview-${this.conversation().id}`);
    protected readonly overdueNote = WAIT_OVERDUE_NOTE;

    private readonly profileService = inject(ProfileService);
    private readonly readMarks = inject(ConversationReadMarksService);
    private readonly locale = inject(LOCALE_ID);

    focus(options?: FocusOptions): void {
        this.selectButton().nativeElement.focus(options);
    }

    protected onKeydown(event: KeyboardEvent): void {
        const move = ROW_MOVES[event.key];
        if (!move) return;
        // The arrows would otherwise scroll the list as well.
        event.preventDefault();
        this.moveRequested.emit(move);
    }

    /**
     * The row's own click opens the conversation; taking it over must not open it as well. The focus moves to the row
     * first: this button goes once the conversation is taken, and a confirm dialog hands the focus back to where it was.
     */
    protected onTakeOver(event: Event): void {
        event.stopPropagation();
        this.focus();
        this.takeOverRequested.emit();
    }
}

// A reason said mid-sentence: "…, resolved by Mike".
function lowerFirst(text: string): string {
    return text.charAt(0).toLowerCase() + text.slice(1);
}
