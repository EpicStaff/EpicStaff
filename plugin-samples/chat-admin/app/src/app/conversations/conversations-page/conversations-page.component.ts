import { DatePipe } from '@angular/common';
import { Component, computed, effect, inject, input, linkedSignal, resource, untracked } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { FormControl, ReactiveFormsModule } from '@angular/forms';
import { Router, RouterLink } from '@angular/router';
import { debounceTime, distinctUntilChanged } from 'rxjs';

import { describeError } from '../../core/describe-error';
import {
    CONVERSATION_ORDERINGS,
    type ConversationListQuery,
    type ConversationOrdering,
    type ConversationPage,
    CONVERSATIONS_PAGE_SIZE,
    DEFAULT_CONVERSATION_ORDERING,
    isConversationOrdering,
} from '../conversation.model';
import { ConversationsApiService } from '../conversations-api.service';

const SEARCH_DEBOUNCE_MS = 300;
const MAX_SEARCH_LENGTH = 512;

/**
 * `/conversations?search=&ordering=&page=`: the plugin's conversations table, most recently
 * updated first by default. Search, sort and page live in the query params, so Back/Forward and a
 * refresh keep them.
 */
@Component({
    selector: 'app-conversations-page',
    imports: [DatePipe, ReactiveFormsModule, RouterLink],
    templateUrl: './conversations-page.component.html',
    styleUrl: './conversations-page.component.css',
})
export class ConversationsPageComponent {
    /** Query params (component input binding). */
    readonly search = input<string>();
    readonly ordering = input<string>();
    readonly page = input<string>();

    protected readonly query = computed<ConversationListQuery>(() => {
        const ordering = this.ordering();
        const page = Number(this.page());
        return {
            search: (this.search() ?? '').slice(0, MAX_SEARCH_LENGTH),
            ordering: isConversationOrdering(ordering) ? ordering : DEFAULT_CONVERSATION_ORDERING,
            page: Number.isSafeInteger(page) && page >= 1 ? page : 1,
        };
    });
    protected readonly conversations = resource({
        params: () => this.query(),
        loader: ({ params, abortSignal }) => this.api.list(params, abortSignal),
    });
    /** The last loaded page, kept on screen (dimmed) while the next one loads. */
    protected readonly listing = linkedSignal<ConversationPage | undefined, ConversationPage | undefined>({
        source: () => (this.conversations.hasValue() ? this.conversations.value() : undefined),
        computation: (next, previous) => next ?? previous?.value,
    });
    protected readonly pageCount = computed(() =>
        Math.max(1, Math.ceil((this.listing()?.count ?? 0) / CONVERSATIONS_PAGE_SIZE))
    );
    protected readonly errorMessage = computed(() => {
        const error = this.conversations.error();
        return error ? describeError(error) : null;
    });

    /** Keeps the search box in step with the URL (Back/Forward change it from outside). */
    private readonly searchSyncEffect = effect(() => {
        const search = this.query().search;
        untracked(() => {
            if (this.searchControl.value !== search) this.searchControl.setValue(search, { emitEvent: false });
        });
    });

    protected readonly orderings = CONVERSATION_ORDERINGS;
    protected readonly searchControl = new FormControl('', { nonNullable: true });

    private readonly api = inject(ConversationsApiService);
    private readonly router = inject(Router);

    constructor() {
        this.searchControl.valueChanges
            .pipe(debounceTime(SEARCH_DEBOUNCE_MS), distinctUntilChanged(), takeUntilDestroyed())
            .subscribe((search) => this.navigate({ search: search.trim() || null, page: null }, true));
    }

    protected setOrdering(event: Event): void {
        const value = (event.target as HTMLSelectElement).value;
        if (!isConversationOrdering(value)) return;
        this.navigate({ ordering: value === DEFAULT_CONVERSATION_ORDERING ? null : value, page: null }, false);
    }

    protected goToPage(page: number): void {
        this.navigate({ page: page <= 1 ? null : page }, false);
    }

    protected isSelected(ordering: ConversationOrdering): boolean {
        return this.query().ordering === ordering;
    }

    /** Typing replaces the history entry; sorting and paging push one, so Back undoes them. */
    private navigate(queryParams: Record<string, string | number | null>, replaceUrl: boolean): void {
        void this.router.navigate([], { queryParams, queryParamsHandling: 'merge', replaceUrl });
    }
}
