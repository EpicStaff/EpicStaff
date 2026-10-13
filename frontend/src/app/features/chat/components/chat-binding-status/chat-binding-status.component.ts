import { Component, computed, input } from '@angular/core';
import { MatTooltipModule } from '@angular/material/tooltip';

import { ChatBinding } from '../../models/chat.model';
import { bindingStatus, CHAT_BINDING_STATUS_LABELS } from '../../utils/binding-status.util';

/** The Live / Paused / Broken pill of a binding; a broken one tells why on hover and keyboard focus. */
@Component({
    selector: 'app-chat-binding-status',
    imports: [MatTooltipModule],
    template: `<span
        class="binding-status"
        matTooltipPosition="below"
        [class]="'binding-status--' + status()"
        [attr.tabindex]="reason() ? 0 : null"
        [matTooltip]="reason() ?? ''"
        [matTooltipDisabled]="!reason()"
        >{{ label() }}</span
    >`,
    styleUrl: './chat-binding-status.component.scss',
})
export class ChatBindingStatusComponent {
    readonly binding = input.required<ChatBinding>();

    readonly status = computed(() => bindingStatus(this.binding()));
    readonly label = computed(() => CHAT_BINDING_STATUS_LABELS[this.status()]);
    // What the operator has to fix; null unless broken.
    protected readonly reason = computed(() => this.binding().broken_reason || null);
}
