import { Component, computed, input } from '@angular/core';

import { ChatConversation } from '../../models/chat.model';
import { visitorAvatarText } from '../../utils/conversation-row.util';
import { avatarColor } from '../../utils/desk-avatar.util';

/**
 * A visitor's round avatar: their number (or a signed visitor's initials) on a fill picked by the conversation id, so
 * the same visitor looks the same in the list and the thread. Decorative: the row it sits in names the visitor.
 */
@Component({
    selector: 'app-conversation-avatar',
    template: `{{ text() }}`,
    styleUrl: './conversation-avatar.component.scss',
    host: {
        'aria-hidden': 'true',
        '[style.background-color]': 'fill()',
    },
})
export class ConversationAvatarComponent {
    readonly conversation = input.required<Pick<ChatConversation, 'id' | 'visitor_number' | 'chat_user_id'>>();

    protected readonly text = computed(() => visitorAvatarText(this.conversation()));
    protected readonly fill = computed(() => avatarColor(this.conversation().id));
}
