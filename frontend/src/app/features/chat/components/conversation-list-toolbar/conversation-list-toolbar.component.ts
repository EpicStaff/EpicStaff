import { Component, computed, input, output, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { MatTooltipModule } from '@angular/material/tooltip';
import { AppSvgIconComponent, ButtonComponent, SearchComponent } from '@shared/components';
import { debounce, distinctUntilChanged, map, of, Subject, timer } from 'rxjs';

import { ConversationListTab } from '../../utils/conversation-list-tab.util';

// Typing settles before the column reloads; clearing does not wait.
export const SEARCH_DEBOUNCE_MS = 250;

/**
 * Above the conversations: a first row with the column's tab switch (projected), and while the column is compact the
 * button that expands it; then the search (server-side, every section of the tab at once) with Mine (Inbox) or New
 * Test Chat (Bot Testing) beside it. It only says what the user chose or asked for; the column decides what that
 * lists, and the page starts a test.
 */
@Component({
    selector: 'app-conversation-list-toolbar',
    imports: [AppSvgIconComponent, ButtonComponent, MatTooltipModule, SearchComponent],
    templateUrl: './conversation-list-toolbar.component.html',
    styleUrl: './conversation-list-toolbar.component.scss',
    host: {
        '[class.conversation-list-toolbar--compact]': 'isCompact()',
    },
})
export class ConversationListToolbarComponent {
    readonly isMineOnly = input.required<boolean>();
    /** Mine needs chats use: without it the toggle is not there. */
    readonly canFilterMine = input(false);
    /** Mine is about Inbox's work: Bot Testing has no Mine. */
    readonly tab = input<ConversationListTab>('inbox');
    /** Why the server refused the search; shown under the field. */
    readonly searchError = input<string | null>(null);
    readonly canCollapse = input(false);
    readonly isCompact = input(false);
    readonly columnId = input<string | null>(null);
    /** New Test Chat is for whoever builds desks, on Bot Testing only. */
    readonly canStartTest = input(false);
    /** Why New Test Chat is disabled now; null while it can start a test. */
    readonly testStartBlockedReason = input<string | null>(null);
    /** The trimmed search, once typing settles; at once when cleared. */
    readonly searchChange = output<string>();
    readonly mineOnlyChange = output<boolean>();
    /** The compact column's button was pressed: the page expands the column. */
    readonly compactToggle = output<void>();
    readonly testStartRequested = output<void>();

    protected readonly searchText = signal('');
    protected readonly showsMine = computed(() => this.canFilterMine() && this.tab() === 'inbox');
    protected readonly showsNewTestChat = computed(() => this.canStartTest() && this.tab() === 'testing');
    protected readonly isFilteredWhileCompact = computed(
        () => this.isCompact() && ((this.showsMine() && this.isMineOnly()) || !!this.searchText().trim())
    );
    protected readonly compactToggleLabel = computed(() =>
        this.isFilteredWhileCompact() ? 'Conversations, filtered' : 'Conversations'
    );

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
}
