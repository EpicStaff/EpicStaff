import { AnimationCallbackEvent } from '@angular/core';

import { ConversationListChange } from './conversation-list.store';

// iOS-like: short, decelerating.
const MOVE_DURATION_MS = 280;
const ENTER_DURATION_MS = 220;
const LEAVE_DURATION_MS = 180;
const EASE_OUT = 'cubic-bezier(0.2, 0, 0, 1)';
const SLIDE = 'translateY(-8px)';
// A move shorter than this is a layout rounding, not a move.
const MIN_MOVE_PX = 1;

export interface ConversationListMotionOptions {
    /** `prefers-reduced-motion: reduce`: nothing animates, everything lands at once. */
    prefersReducedMotion: () => boolean;
    /** Whether a conversation is shown once the current change has rendered (in an open section, in the loaded rows). */
    isShown: (conversationId: string) => boolean;
    /** Puts the focus on a conversation's row without scrolling: the motion scrolls it into view once it has slid. */
    restoreFocus: (conversationId: string) => void;
    /** Puts the focus on a section's header, in view: the focused row left and no row is shown to take the focus. */
    focusSectionHeader: (section: string) => void;
}

interface Batch {
    kind: ConversationListChange;
    /** Where each row was on screen before the change, by conversation id (live batches only). */
    rects: Map<string, DOMRect>;
    /** The conversation whose row held the focus before the change. */
    focusedId: string | null;
    focusedElement: Element | null;
    /** Where the focus goes if its row leaves the shown rows: the rows in order before the change, and its section. */
    idsBefore: string[];
    focusedSection: string | null;
    /** The focus was inside a row that is going: its conversation's row, if still shown, gets the focus back. */
    isFocusLeaving: boolean;
    played: boolean;
}

/**
 * The conversations column's motion: a conversation that changes place slides there (FLIP with the Web Animations
 * API, keyed by its id), one that arrives fades in and one that goes fades out. Only live changes move; loads,
 * paging, reloads and collapsing land at once. Changes that render together are one batch.
 *
 * The column calls `note()` on every change before it renders, `play()` after the render (in its read phase, so after
 * Angular has run every `animate.enter` and `animate.leave` of that render), and binds `enter()` and `leave()` to each
 * row's `animate.enter` and `animate.leave`. A row that moves between sections is re-created, so its enter and leave
 * are skipped: its slide covers it.
 */
export class ConversationListMotion {
    private batch: Batch | null = null;
    private readonly running = new Map<Element, Animation>();

    constructor(private readonly options: ConversationListMotionOptions) {}

    /**
     * A change is about to render. The first one of a batch records where the rows are (`rows` is read only then);
     * a load anywhere in a batch keeps the whole batch still. Returns true when this started a batch: the caller then
     * calls `play()` after the render.
     */
    note(kind: ConversationListChange, rows: () => Iterable<HTMLElement>): boolean {
        if (this.batch && !this.batch.played) {
            if (kind === 'load') this.batch.kind = 'load';
            return false;
        }
        if (kind === 'load') this.finishRunning();
        const focused = document.activeElement;
        const focusedRow = focused?.closest<HTMLElement>('[data-id]') ?? null;
        const focusedId = focusedRow?.dataset['id'] ?? null;
        const slides = kind === 'live' && !this.options.prefersReducedMotion();
        const before = slides || focusedId ? [...rows()] : [];
        this.batch = {
            kind,
            rects: slides ? measure(before) : new Map(),
            focusedId,
            focusedElement: focused,
            idsBefore: focusedId ? before.map((row) => row.dataset['id'] ?? '') : [],
            focusedSection: focusedRow?.closest<HTMLElement>('[data-section]')?.dataset['section'] ?? null,
            isFocusLeaving: false,
            played: false,
        };
        return true;
    }

    /**
     * After the batch rendered: slide each moved row from where it was, and keep the focus in the list when its row
     * went. A moved row gets it back; a row no longer shown hands it to the next shown row (the previous one at the
     * end), or to its section's header when no row is left. The row that takes it is brought into view once it has
     * slid.
     */
    play(rows: Iterable<HTMLElement>): void {
        const batch = this.batch;
        if (!batch || batch.played) return;
        batch.played = true;
        const shownRows = [...rows];
        if (batch.kind === 'live' && !this.options.prefersReducedMotion()) {
            for (const row of shownRows) this.slide(row, batch.rects.get(row.dataset['id'] ?? ''));
        }
        const { focusedId, focusedElement } = batch;
        // The old row is still in the document here in a browser (Angular removes it once its leave settles); without
        // leave listeners (no Web Animations) it is already gone.
        const hasFocusGone = batch.isFocusLeaving || !focusedElement?.isConnected;
        if (!focusedId || !hasFocusGone) return;
        const target = this.options.isShown(focusedId) ? focusedId : this.shownNeighbour(batch.idsBefore, focusedId);
        if (target) {
            this.options.restoreFocus(target);
            this.revealAfterSlide(shownRows.find((row) => row.dataset['id'] === target));
        } else if (batch.focusedSection) {
            this.options.focusSectionHeader(batch.focusedSection);
        }
    }

    /** A row was added: it fades in when a live change brought it from outside the shown rows. */
    enter(event: AnimationCallbackEvent, conversationId: string): void {
        const batch = this.batch;
        if (batch?.kind !== 'live' || batch.rects.has(conversationId) || this.options.prefersReducedMotion()) return;
        if (typeof event.target.animate !== 'function') return;
        this.track(
            event.target,
            event.target.animate(
                [
                    { opacity: 0, transform: SLIDE },
                    { opacity: 1, transform: 'none' },
                ],
                {
                    duration: ENTER_DURATION_MS,
                    easing: EASE_OUT,
                }
            )
        );
    }

    /**
     * A row is going: it fades out when a live change took it out of the shown rows (into a collapsed section, past a
     * section's loaded end). Out of the flow while it fades, so the rows below slide up at once. Anything else, a moved
     * row included, goes at once: hidden now, since Angular removes it only after this render, when `play()` has
     * already measured where the rows landed.
     */
    leave(event: AnimationCallbackEvent, conversationId: string): void {
        const batch = this.batch;
        const element = event.target as HTMLElement;
        if (batch?.focusedElement && element.contains(batch.focusedElement)) batch.isFocusLeaving = true;
        const fades =
            batch?.kind === 'live' &&
            !this.options.isShown(conversationId) &&
            !this.options.prefersReducedMotion() &&
            typeof element.animate === 'function';
        if (!fades) {
            element.style.display = 'none';
            event.animationComplete();
            return;
        }
        // A slide still running on it would stack its transform with the fade's.
        this.running.get(element)?.cancel();
        const { offsetTop, offsetWidth } = element;
        Object.assign(element.style, {
            position: 'absolute',
            top: `${offsetTop}px`,
            left: '0',
            width: `${offsetWidth}px`,
            pointerEvents: 'none',
        });
        const animation = element.animate([{ opacity: 1 }, { opacity: 0, transform: SLIDE }], {
            duration: LEAVE_DURATION_MS,
            easing: EASE_OUT,
        });
        this.track(element, animation, () => event.animationComplete());
    }

    /** The column goes away: nothing keeps moving. */
    destroy(): void {
        this.finishRunning();
        this.batch = null;
    }

    private slide(row: HTMLElement, first: DOMRect | undefined): void {
        if (!first || typeof row.animate !== 'function') return;
        // Measured without the transform of a slide still running, which `first` already included.
        this.running.get(row)?.cancel();
        const last = row.getBoundingClientRect();
        const offset = first.top - last.top;
        if (Math.abs(offset) < MIN_MOVE_PX) return;
        this.track(
            row,
            row.animate([{ transform: `translateY(${offset}px)` }, { transform: 'none' }], {
                duration: MOVE_DURATION_MS,
                easing: EASE_OUT,
            })
        );
    }

    /** The first row after `id` that is still shown, in the order before the change; else the last one before it. */
    private shownNeighbour(idsBefore: string[], id: string): string | null {
        const index = idsBefore.indexOf(id);
        const isShown = (candidate: string): boolean => this.options.isShown(candidate);
        return (
            idsBefore.slice(index + 1).find(isShown) ??
            idsBefore.slice(0, Math.max(index, 0)).reverse().find(isShown) ??
            null
        );
    }

    /**
     * The focus came back with `preventScroll` (a jump mid-slide would fight it): once the row has slid into place it
     * is scrolled into view if it is not, below the stuck header (the column's scroll padding).
     */
    private revealAfterSlide(row: HTMLElement | undefined): void {
        if (!row) return;
        const reveal = (): void => row.scrollIntoView({ block: 'nearest' });
        const slide = this.running.get(row);
        if (!slide) {
            reveal();
            return;
        }
        // A slide cancelled by a newer change leaves the reveal to that change.
        slide.finished.then(reveal, () => undefined);
    }

    private track(element: Element, animation: Animation, onEnd?: () => void): void {
        this.running.set(element, animation);
        const end = (): void => {
            if (this.running.get(element) === animation) this.running.delete(element);
            onEnd?.();
        };
        animation.onfinish = end;
        animation.oncancel = end;
    }

    // Finishing (not cancelling) lets a fading row complete its leave and be removed.
    private finishRunning(): void {
        for (const animation of [...this.running.values()]) animation.finish();
        this.running.clear();
    }
}

function measure(rows: Iterable<HTMLElement>): Map<string, DOMRect> {
    const rects = new Map<string, DOMRect>();
    for (const row of rows) {
        const id = row.dataset['id'];
        if (id) rects.set(id, row.getBoundingClientRect());
    }
    return rects;
}
