import { Component, computed, effect, inject, input, output, signal, untracked, viewChildren } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { ButtonComponent, ListComponent, SectionHeaderComponent, SpinnerComponent } from '@shared/components';
import { ActionCode, ResourceCode } from '@shared/models';
import { interval } from 'rxjs';

import { PermissionsService } from '../../../../services/auth/permissions.service';
import { ChatConversation, ChatInboxSection } from '../../models/chat.model';
import { ChatConversationActionsService } from '../../services/chat-conversation-actions.service';
import { ChatDesksStorageService } from '../../services/chat-desks-storage.service';
import { ChatInboxStreamService } from '../../services/chat-inbox-stream.service';
import { visitorName } from '../../utils/conversation-row.util';
import { ConversationRowComponent, ConversationRowMove } from '../conversation-row/conversation-row.component';
import { ConversationListStore } from './conversation-list.store';

// Relative times ("6m") move on without a reload.
const NOW_TICK_MS = 30_000;

/**
 * The conversations column: today's three sections (Needs a human, Bot, Tests) of one desk, or of every desk. Loads
 * and pages them, keeps them live, and moves the selection with ↑/↓ (one row is the Tab stop).
 */
@Component({
    selector: 'app-conversation-list',
    imports: [ButtonComponent, ListComponent, SectionHeaderComponent, SpinnerComponent, ConversationRowComponent],
    providers: [ConversationListStore],
    templateUrl: './conversation-list.component.html',
    styleUrl: './conversation-list.component.scss',
})
export class ConversationListComponent {
    /** The desk listed; null lists every desk. */
    readonly bindingId = input<string | null>(null);
    readonly selectedId = input<string | null>(null);
    readonly selectedChange = output<ChatConversation>();

    private readonly rows = viewChildren(ConversationRowComponent);

    /** The list's own copy of the selected conversation: refetched on every reload. Null while it does not list it. */
    readonly selectedRow = computed(() => this.store.findRow(this.selectedId()));
    protected readonly now = signal(Date.now());
    protected readonly canTakeOver = computed(() => this.permissionsService.can(ResourceCode.Chats, ActionCode.Use));
    /** Every desk's name by id, on All desks only: each row says which desk it came in on. */
    protected readonly deskNames = computed((): ReadonlyMap<string, string> | null =>
        this.bindingId() ? null : new Map(this.desksStorage.desks().map((desk) => [desk.id, desk.name]))
    );
    /** The row Tab lands on: the selected one when it is shown, else the first. */
    protected readonly tabStopId = computed(() => {
        const rows = this.store.visibleRows();
        const selectedId = this.selectedId();
        return rows.some((row) => row.id === selectedId) ? selectedId : (rows[0]?.id ?? null);
    });
    /** Said once each time the open conversation's bot starts replying; nothing while it is not. */
    protected readonly replyingAnnouncement = computed(() => {
        const row = this.store.findRow(this.selectedId());
        return row?.state === 'processing' ? `Bot is replying to ${visitorName(row)}` : '';
    });

    /** Every `ready` means the stream is live from now, so a reload after it is complete; so does another desk. */
    private readonly reloadOnReadyOrScope = effect(() => {
        this.chatInboxStream.readyEpoch();
        const bindingId = this.bindingId();
        untracked(() => this.store.reload(bindingId));
    });

    protected readonly store = inject(ConversationListStore);
    protected readonly isActionPending = inject(ChatConversationActionsService).isPending;
    protected readonly ResourceCode = ResourceCode;
    protected readonly trackConversation = (_index: number, row: ChatConversation): string => row.id;

    private readonly permissionsService = inject(PermissionsService);
    private readonly desksStorage = inject(ChatDesksStorageService);
    private readonly chatInboxStream = inject(ChatInboxStreamService);
    private readonly conversationActions = inject(ChatConversationActionsService);

    constructor() {
        interval(NOW_TICK_MS)
            .pipe(takeUntilDestroyed())
            .subscribe(() => this.now.set(Date.now()));
    }

    /** Expands a section so a conversation in it shows, e.g. Tests when a test conversation starts. */
    reveal(section: ChatInboxSection): void {
        this.store.expand(section);
    }

    protected takeOver(row: ChatConversation): void {
        this.conversationActions.takeOver(row);
    }

    /** ↑/↓/Home/End: focus and open the row it leads to, among the rows shown. */
    protected move(from: ChatConversation, move: ConversationRowMove): void {
        const rows = this.store.visibleRows();
        const index = rows.findIndex((row) => row.id === from.id);
        const targetIndex =
            move === 'first' ? 0 : move === 'last' ? rows.length - 1 : index + (move === 'next' ? 1 : -1);
        const target = rows[targetIndex];
        if (!target || target.id === from.id) return;
        this.rows()
            .find((row) => row.conversation().id === target.id)
            ?.focus();
        this.selectedChange.emit(target);
    }
}
