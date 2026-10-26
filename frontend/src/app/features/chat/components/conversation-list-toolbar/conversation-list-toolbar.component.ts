import { Component, computed, input, output, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { MatTooltipModule } from '@angular/material/tooltip';
import { AppSvgIconComponent, SearchComponent } from '@shared/components';
import { debounce, distinctUntilChanged, map, of, Subject, timer } from 'rxjs';

import { ChatInboxOrder } from '../../models/chat.model';

// Typing settles before the column reloads; clearing does not wait.
export const SEARCH_DEBOUNCE_MS = 250;

const ORDER_LABELS: Record<ChatInboxOrder, string> = { newest: 'Newest first', oldest: 'Oldest first' };

/**
 * Above the conversations: the search (server-side, every section at once), Mine and the sort order. It only says what
 * the user chose; the column decides what that lists.
 */
@Component({
    selector: 'app-conversation-list-toolbar',
    imports: [AppSvgIconComponent, MatTooltipModule, SearchComponent],
    templateUrl: './conversation-list-toolbar.component.html',
    styleUrl: './conversation-list-toolbar.component.scss',
    host: {
        '[class.conversation-list-toolbar--compact]': 'isCompact()',
    },
})
export class ConversationListToolbarComponent {
    readonly order = input.required<ChatInboxOrder>();
    readonly isMineOnly = input.required<boolean>();
    /** Mine needs chats use: without it the toggle is not there. */
    readonly canFilterMine = input(false);
    /** Why the server refused the search; shown under the field. */
    readonly searchError = input<string | null>(null);
    readonly canCollapse = input(false);
    readonly isCompact = input(false);
    readonly columnId = input<string | null>(null);
    /** The trimmed search, once typing settles; at once when cleared. */
    readonly searchChange = output<string>();
    readonly orderChange = output<ChatInboxOrder>();
    readonly mineOnlyChange = output<boolean>();
    readonly compactToggle = output<void>();

    protected readonly searchText = signal('');
    protected readonly isFilteredWhileCompact = computed(
        () => this.isCompact() && (this.isMineOnly() || !!this.searchText().trim())
    );
    protected readonly compactToggleLabel = computed(() =>
        this.isFilteredWhileCompact() ? 'Conversations, filtered' : 'Conversations'
    );
    protected readonly orderLabel = computed(() => ORDER_LABELS[this.order()]);
    // Says what the button is, and still starts with what it shows (the label is in the name).
    protected readonly sortName = computed(() => `Sort: ${this.orderLabel().toLowerCase()}`);

    private readonly typedSearches = new Subject<string>();

    constructor() {
        this.typedSearches
            .pipe(
                map((text) => text.trim()),
                debounce((search) => (search ? timer(SEARCH_DEBOUNCE_MS) : of(search))),
                distinctUntilChanged(),
                takeUntilDestroyed()
            )
            .subscribe((search) => this.searchChange.emit(search));
    }

    /** Empties the field and lists without searching at once; Escape and the field's clear button do the same. */
    clearSearch(): void {
        this.onSearchText('');
    }

    protected onSearchText(text: string): void {
        this.searchText.set(text);
        this.typedSearches.next(text);
    }

    /** Escape clears a search; with nothing typed it is left to whoever else listens. */
    protected onEscape(event: Event): void {
        if (!this.searchText()) return;
        event.stopPropagation();
        this.clearSearch();
    }

    protected toggleOrder(): void {
        this.orderChange.emit(this.order() === 'newest' ? 'oldest' : 'newest');
    }
}
