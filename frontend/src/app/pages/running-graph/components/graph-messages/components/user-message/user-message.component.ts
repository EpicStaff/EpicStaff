import { CommonModule } from '@angular/common';
import { Component, Input } from '@angular/core';

import { GraphMessage, MessageType, UserMessageData } from '../../../../models/graph-session-message.model';

@Component({
    selector: 'app-user-message',
    standalone: true,
    imports: [CommonModule],
    template: `
        <div class="user-message-container">
            <div class="message-bubble">
                <span class="message-text">{{ getMessageText() }}</span>
            </div>
        </div>
    `,
    styles: [
        `
            .user-message-container {
                display: flex;
                justify-content: flex-end;
                position: relative;
            }

            .message-bubble {
                background-color: #ffa726;
                border-radius: 18px 18px 0 18px;
                padding: 0.75rem 1rem;
                color: var(--gray-900);
                max-width: 85%;
                word-break: break-word;
                box-shadow: 0 1px 2px rgba(0, 0, 0, 0.15);
            }

            .message-text {
                color: var(--gray-900);
                white-space: pre-wrap;
            }
        `,
    ],
})
export class UserMessageComponent {
    @Input() message!: GraphMessage;

    get userMessageData(): UserMessageData | null {
        if (this.message.message_data && this.message.message_data.message_type === MessageType.USER) {
            return this.message.message_data as UserMessageData;
        }
        return null;
    }
    //workaround
    getMessageText(): string {
        if (this.userMessageData?.text === '</done/>') {
            return 'Done';
        }
        return this.userMessageData?.text || '';
    }
}
