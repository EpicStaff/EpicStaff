import { Component, computed, ElementRef, inject, input, viewChild } from '@angular/core';
import { MatTooltipModule } from '@angular/material/tooltip';
import { AppSvgIconComponent, ButtonComponent } from '@shared/components';
import { ActionCode, ResourceCode } from '@shared/models';

import { PhoneLayoutService } from '../../../../core/services/phone-layout.service';
import { PermissionsService } from '../../../../services/auth/permissions.service';
import { ProfileService } from '../../../../services/auth/profile.service';
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
import { operatorName, visitorName } from '../../utils/conversation-row.util';
import { ChatActionMenuComponent, ChatActionMenuItem } from '../chat-action-menu/chat-action-menu.component';
import { ChatUsageRingComponent } from '../chat-usage-ring/chat-usage-ring.component';

/**
 * The open conversation's header: its mode (or Closed), title, Test chip, today's usage against its desk's limits and
 * the holder's actions. On phones it is also the thread screen's nav bar: Back to the list, the visitor and the ⋯ menu.
 */
@Component({
    selector: 'app-chat-thread-header',
    imports: [MatTooltipModule, AppSvgIconComponent, ButtonComponent, ChatActionMenuComponent, ChatUsageRingComponent],
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

    private readonly threadBack = viewChild<ElementRef<HTMLButtonElement>>('threadBack');

    readonly canUse = computed(() => this.permissionsService.can(ResourceCode.Chats, ActionCode.Use));
    readonly isClosed = computed(() => isClosed(this.conversation()));
    /** The thread's Back on phones, named after the list it returns to. */
    readonly backText = computed(() => this.listTitle() || 'Back');
    readonly backLabel = computed(() => {
        const title = this.listTitle();
        return title ? `Back to ${title}` : 'Back';
    });
    // Who holds the open conversation, for the mode pill's tooltip: "you", their name or "Operator #7"; null while
    // nobody does, and once it is closed.
    readonly holderLabel = computed(() => {
        const conversation = this.conversation();
        const operatorId = conversation.assigned_operator_id ?? null;
        if (operatorId === null || isClosed(conversation)) return null;
        if (operatorId === this.profileService.currentUserSignal()?.id) return 'you';
        return operatorName(operatorId, conversation.assigned_operator_name ?? null);
    });
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
    /** The holder's main action, a button beside the title (see `primaryConversationAction`). */
    readonly primaryAction = computed(() => primaryConversationAction(this.actionContext()));
    /** The conversation's other actions, in its ⋯ menu (see `conversationMenuItems`). */
    readonly conversationMenuItems = computed((): ChatActionMenuItem<ConversationAction>[] =>
        conversationMenuItems(this.actionContext())
    );

    protected readonly isActionPending = inject(ChatConversationActionsService).isPending;
    protected readonly isPhone = inject(PhoneLayoutService).isPhone;
    protected readonly openConversation = inject(OpenConversationService);
    protected readonly visitorName = visitorName;

    private readonly conversationActions = inject(ChatConversationActionsService);
    private readonly permissionsService = inject(PermissionsService);
    private readonly profileService = inject(ProfileService);

    runConversationAction(action: ConversationAction): void {
        const conversation = this.conversation();
        const run: Record<ConversationAction, () => void> = {
            'take-over': () => this.conversationActions.takeOver(conversation),
            release: () => this.conversationActions.release(conversation),
            resolve: () => this.conversationActions.resolve(conversation),
            close: () => this.conversationActions.closeConversation(conversation),
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
}
