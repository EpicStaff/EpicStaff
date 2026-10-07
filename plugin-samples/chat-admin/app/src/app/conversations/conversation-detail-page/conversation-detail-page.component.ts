import { DatePipe, JsonPipe } from '@angular/common';
import { Component, computed, inject, input, resource } from '@angular/core';
import { RouterLink } from '@angular/router';

import { describeError } from '../../core/describe-error';
import { type ConversationLookup, ConversationsApiService } from '../conversations-api.service';
import { isTableKey } from '../conversation.model';
import { TranscriptComponent } from '../transcript/transcript.component';

/** `/conversations/:key`: one stored conversation, read-only, with a way to continue it in Chat. */
@Component({
    selector: 'app-conversation-detail-page',
    imports: [DatePipe, JsonPipe, RouterLink, TranscriptComponent],
    templateUrl: './conversation-detail-page.component.html',
    styleUrl: './conversation-detail-page.component.css',
})
export class ConversationDetailPageComponent {
    /** Route param `:key` (component input binding). */
    readonly key = input.required<string>();

    protected readonly validKey = computed(() => isTableKey(this.key()));
    protected readonly lookup = resource<ConversationLookup, string | undefined>({
        params: () => (this.validKey() ? this.key() : undefined),
        loader: ({ params }) => this.api.get(params),
    });
    protected readonly errorMessage = computed(() => {
        const error = this.lookup.error();
        return error ? describeError(error) : null;
    });

    private readonly api = inject(ConversationsApiService);
}
