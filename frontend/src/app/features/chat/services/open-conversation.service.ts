import { Location } from '@angular/common';
import { computed, DestroyRef, effect, inject, Injectable, signal, untracked } from '@angular/core';
import { takeUntilDestroyed, toSignal } from '@angular/core/rxjs-interop';
import { ActivatedRoute, NavigationSkipped, NavigationStart, Router, UrlTree } from '@angular/router';
import { isNavigationOver, NavigationOver } from '@shared/utils';
import { map } from 'rxjs';

import { PhoneLayoutService } from '../../../core/services/phone-layout.service';
import { ChatConversation } from '../models/chat.model';

/** The query parameter naming the open conversation. */
export const CONVERSATION_QUERY_PARAM = 'conversation';
/** Marks the history entry this page pushed to open a thread on a phone: its Back can go back through history. */
export const THREAD_ENTRY_STATE = 'chatThreadEntry';
/**
 * Wider screens write the URL once the selection has rested this long. Holding ↑/↓ would otherwise replace the history
 * entry on every key repeat, and WebKit refuses history calls beyond about a hundred in ten seconds.
 */
export const URL_WRITE_DELAY_MS = 250;

/**
 * Which conversation the chat page has open, kept in the URL (`?conversation=<id>`) so that a reload or a link
 * reopens it, and the history that comes with it on phones, where the conversations and the thread are a navigation
 * stack: going from the list into a thread pushes an entry, so the browser's back (Safari's edge swipe, Android's back)
 * returns to the list. Every other change replaces the entry; on wider screens only once the selection rests.
 *
 * What is open shows at once: an open or close made here is the open id until the URL says the same, and a navigation
 * made elsewhere (a link, history) overrides it. The row of the open conversation is kept here too, as it was selected,
 * found in the list or streamed. Provided by the chat page.
 */
@Injectable()
export class OpenConversationService {
    private readonly router = inject(Router);
    private readonly route = inject(ActivatedRoute);
    private readonly location = inject(Location);
    private readonly isPhone = inject(PhoneLayoutService).isPhone;

    /** The id in the URL. */
    readonly urlId = toSignal(this.route.queryParamMap.pipe(map((params) => params.get(CONVERSATION_QUERY_PARAM))), {
        requireSync: true,
    });
    // An open or a close made here that the URL does not say yet.
    private readonly requested = signal<{ id: string | null } | null>(null);
    /** The open conversation's id: the one just opened or closed here, else the URL's. */
    readonly id = computed(() => {
        const requested = this.requested();
        return requested ? requested.id : this.urlId();
    });
    private readonly held = signal<ChatConversation | null>(null);
    /** The open conversation's row as last known; null while the open id has none yet (a link, a reload). */
    readonly row = computed(() => {
        const held = this.held();
        return held && held.id === this.id() ? held : null;
    });
    private readonly isStackAnimatedSignal = signal(false);
    /**
     * Phones: whether the stack's next move (the thread pushing in or popping out) slides. Only the moves made here do:
     * a move through history was animated by the browser already (Safari's edge swipe) or should not be (Android's
     * back, a reload).
     */
    readonly isStackAnimated = this.isStackAnimatedSignal.asReadonly();

    /**
     * The thread's Back is on its way through history: the popstate that follows is this page's own move (its
     * navigation, once started), and a conversation opened meanwhile waits for it to land.
     */
    private readonly ownBack = signal<{ navigationId: number | null; queuedId: string | null } | null>(null);

    // A request is done once the URL says the same; not while a Back is on its way, whose landing changes the URL.
    private readonly settleRequest = effect(() => {
        const requested = this.requested();
        if (requested && requested.id === this.urlId() && !this.ownBack()) {
            untracked(() => this.requested.set(null));
        }
    });
    // Closed, the row goes: history forward to it then takes the list's fresh row, not one that stopped updating.
    private readonly forgetRowOnClose = effect(() => {
        if (this.id() === null) untracked(() => this.held.set(null));
    });

    private writeTimer: ReturnType<typeof setTimeout> | null = null;
    // The URL of the last write made here, to tell its navigation from anyone else's.
    private ownWriteUrl: string | null = null;
    constructor() {
        this.router.events.pipe(takeUntilDestroyed()).subscribe((event) => {
            if (event instanceof NavigationStart) this.onNavigationStart(event);
            else if (isNavigationOver(event) && this.isOwnBackOver(event)) this.onOwnBackLanded(event);
        });
        inject(DestroyRef).onDestroy(() => this.cancelWrite());
    }

    /**
     * Opens a conversation (a row, a started test). Phones: from the list (or from an id the list never resolved) into
     * the thread is a push that slides; replacing the thread shown is not. It shows at once, even while the thread's
     * Back is still on its way through history; its URL is then written once that Back has landed.
     */
    open(conversation: ChatConversation): void {
        const shown = this.row();
        this.held.set(conversation);
        const id = conversation.id;
        if (id === shown?.id) return;
        this.cancelWrite();
        this.requested.set({ id });
        if (!this.isPhone()) {
            this.writeLater(id);
            return;
        }
        if (!shown) this.isStackAnimatedSignal.set(true);
        // Tapped while the thread's Back is still on its way: the entry it lands on decides push or replace.
        if (this.ownBack()) {
            this.ownBack.update((back) => back && { ...back, queuedId: id });
            return;
        }
        this.writeOnPhone(id, !!shown);
    }

    /**
     * The thread's Back (phones): through history when this page pushed the thread, so the user lands on the list's
     * own entry rather than a copy; else the id leaves the URL in place. Either way the user stays in the chat area.
     * While a Back is on its way it never goes back again (two backs would leave the page): it only closes a
     * conversation opened meanwhile.
     */
    close(): void {
        if (this.id() === null) return;
        this.isStackAnimatedSignal.set(true);
        this.cancelWrite();
        if (this.ownBack()) {
            // Back on a conversation opened while the previous Back was on its way: it is not opened after all.
            this.ownBack.update((back) => back && { ...back, queuedId: null });
            this.requested.set({ id: null });
            return;
        }
        if (!this.isThreadEntry()) {
            this.drop();
            return;
        }
        this.ownBack.set({ navigationId: null, queuedId: null });
        this.requested.set({ id: null });
        this.location.back();
    }

    /** Closes the open conversation and takes its id out of the URL in place, without a history entry. */
    drop(): void {
        this.cancelWrite();
        this.held.set(null);
        if (this.urlId() === null) {
            this.requested.set(null);
            return;
        }
        this.requested.set({ id: null });
        this.write(null, false);
    }

    /** Forgets the row and any change not in the URL yet; the URL's own id stays (a desk change brought it along). */
    forget(): void {
        this.cancelWrite();
        this.requested.set(null);
        this.held.set(null);
    }

    /** A newer row of the open conversation (streamed, returned by an action, found in the list); others are ignored. */
    remember(row: ChatConversation): void {
        if (row.id === this.id()) this.held.set(row);
    }

    /** The stack has slid: its next move is instant unless one made here asks again. */
    stackSlid(): void {
        this.isStackAnimatedSignal.set(false);
    }

    private onNavigationStart(event: NavigationStart): void {
        if (event.navigationTrigger === 'popstate') {
            const back = this.ownBack();
            if (back && back.navigationId === null) {
                this.ownBack.set({ ...back, navigationId: event.id });
                return;
            }
            this.isStackAnimatedSignal.set(false);
        } else if (event.url === this.ownWriteUrl) {
            return;
        }
        // A navigation made elsewhere (a link, history): the URL it brings decides what is open.
        this.cancelWrite();
        this.requested.set(null);
    }

    /**
     * The Back's own navigation is over. So is a navigation skipped before the Back's started: the router skips a
     * popstate onto an entry with the URL already shown, and no NavigationStart comes for it.
     */
    private isOwnBackOver(event: NavigationOver): boolean {
        const back = this.ownBack();
        if (!back) return false;
        return back.navigationId === null ? event instanceof NavigationSkipped : event.id === back.navigationId;
    }

    /**
     * The Back has landed: a conversation opened meanwhile is written from the entry it landed on, as from the list.
     * Else the URL decides what is open, unless the router skipped the move: then the URL still names the conversation
     * just closed, and loses it in place.
     */
    private onOwnBackLanded(event: NavigationOver): void {
        const queuedId = this.ownBack()?.queuedId ?? null;
        this.ownBack.set(null);
        if (queuedId !== null && queuedId === this.id()) {
            this.writeOnPhone(queuedId, false);
        } else if (event instanceof NavigationSkipped && this.urlId() !== null) {
            this.requested.set({ id: null });
            this.write(null, false);
        } else {
            this.requested.set(null);
        }
    }

    /**
     * A thread replaces a thread, and a thread entry whose id the list never resolved stays the thread entry it was.
     * From the list, the thread gets an entry of its own; an id the list never resolved leaves the entry below first,
     * or the browser's back would land on it and reopen it.
     */
    private writeOnPhone(id: string, isThreadShown: boolean): void {
        if (isThreadShown || this.isThreadEntry()) {
            this.write(id, false);
            return;
        }
        if (this.urlId() !== null) this.removeIdFromEntry();
        this.write(id, true);
    }

    private writeLater(id: string): void {
        this.writeTimer = setTimeout(() => {
            this.writeTimer = null;
            this.write(id, false);
        }, URL_WRITE_DELAY_MS);
    }

    private write(id: string | null, isPush: boolean): void {
        // Nothing to replace when the URL says it already; a push always writes (its entry may just have been stripped).
        if (!isPush && id === this.urlId()) return;
        // A thread entry keeps its mark while another conversation replaces it, so Back still goes through history.
        const isThreadEntry = id !== null && (isPush || this.isThreadEntry());
        const target = this.urlWith(id);
        this.ownWriteUrl = this.router.serializeUrl(target);
        void this.router.navigateByUrl(target, {
            replaceUrl: !isPush,
            state: isThreadEntry ? { [THREAD_ENTRY_STATE]: true } : undefined,
        });
    }

    // Behind the router's back, keeping the entry's state: the router moves on from it with the push that follows.
    private removeIdFromEntry(): void {
        this.location.replaceState(this.router.serializeUrl(this.urlWith(null)), '', this.location.getState());
    }

    private urlWith(id: string | null): UrlTree {
        return this.router.createUrlTree([], {
            relativeTo: this.route,
            queryParams: { [CONVERSATION_QUERY_PARAM]: id },
            queryParamsHandling: 'merge',
        });
    }

    /** Whether the current history entry is a thread this page pushed (the browser keeps it across a reload). */
    private isThreadEntry(): boolean {
        const state: unknown = this.location.getState();
        return (
            typeof state === 'object' &&
            state !== null &&
            (state as Record<string, unknown>)[THREAD_ENTRY_STATE] === true
        );
    }

    private cancelWrite(): void {
        if (this.writeTimer !== null) clearTimeout(this.writeTimer);
        this.writeTimer = null;
    }
}
