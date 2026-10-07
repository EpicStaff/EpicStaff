import { DatePipe } from '@angular/common';
import { Component, input } from '@angular/core';

import type { ConversationMessage } from '../conversation.model';

/** A conversation's messages, oldest first. Shared by the chat and the transcript page. */
@Component({
    selector: 'app-transcript',
    imports: [DatePipe],
    templateUrl: './transcript.component.html',
    styleUrl: './transcript.component.css',
})
export class TranscriptComponent {
    readonly messages = input.required<readonly ConversationMessage[]>();
    /** Shows a "Thinking…" bubble after the last message. */
    readonly pending = input(false);
}
