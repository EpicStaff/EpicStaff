import { Component, computed, input } from '@angular/core';

import { ChatBinding } from '../../models/chat.model';
import { bindingStatus, CHAT_BINDING_STATUS_LABELS } from '../../utils/binding-status.util';

/** The Live / Paused / Broken pill of a binding. */
@Component({
    selector: 'app-chat-binding-status',
    template: `<span
        class="binding-status"
        [class]="'binding-status--' + status()"
        >{{ label() }}</span
    >`,
    styleUrl: './chat-binding-status.component.scss',
})
export class ChatBindingStatusComponent {
    readonly binding = input.required<ChatBinding>();

    readonly status = computed(() => bindingStatus(this.binding()));
    readonly label = computed(() => CHAT_BINDING_STATUS_LABELS[this.status()]);
}
