import { InteractivityChecker, LiveAnnouncer } from '@angular/cdk/a11y';
import { DOCUMENT } from '@angular/common';
import { inject, NgZone } from '@angular/core';

/**
 * The keyboard side of a tour step.
 *
 * - Tab and Shift+Tab cycle between the popover and the highlighted target. CDK's FocusTrap keeps the focus in one
 *   region only, hence a cycle of our own.
 * - Escape is reported (`onEscape`); whether it closes the tour is the tour's decision.
 *
 * Both act only while the focus is in the popover or the target, so an overlay opened mid-step (e.g. a route guard's
 * CDK dialog) keeps its own focus trap and Escape. Overlay keydown events are not used: CDK hands them to the
 * last-attached overlay with a listener, not the one on top of the browser's top layer.
 */
export class TourFocusCycle {
    private readonly document = inject(DOCUMENT);
    private readonly interactivityChecker = inject(InteractivityChecker);
    private readonly liveAnnouncer = inject(LiveAnnouncer);
    private readonly ngZone = inject(NgZone);
    private popover: HTMLElement | null = null;
    private target: Element | null = null;

    /** Tab from either region, and Escape from the target (bubble phase, after the target's own handlers). */
    private readonly onDocumentKeydown = (event: KeyboardEvent): void => {
        const origin = event.target;
        if (
            event.defaultPrevented ||
            !(origin instanceof Node) ||
            (!this.isInPopover(origin) && !this.isInTarget(origin))
        ) {
            return;
        }
        if (event.key === 'Tab' && !event.altKey && !event.ctrlKey && !event.metaKey) {
            this.moveFocus(event);
        } else if (event.key === 'Escape' && this.isInTarget(origin)) {
            this.ngZone.run(() => this.onEscape());
        }
    };

    /**
     * Escape from the popover. Stopped here, before CDK's keyboard dispatcher on <body>: it would hand the key to an
     * overlay open beneath the tour, e.g. close a dialog the user cannot see is focused.
     */
    private readonly onPopoverKeydown = (event: KeyboardEvent): void => {
        if (event.key !== 'Escape' || event.defaultPrevented) {
            return;
        }
        event.preventDefault();
        event.stopPropagation();
        this.ngZone.run(() => this.onEscape());
    };

    constructor(private readonly onEscape: () => void) {}

    /** Starts listening; `popover` is the element that holds the step card. */
    attach(popover: HTMLElement): void {
        if (this.popover) {
            return;
        }
        this.popover = popover;
        this.ngZone.runOutsideAngular(() => {
            popover.addEventListener('keydown', this.onPopoverKeydown);
            this.document.addEventListener('keydown', this.onDocumentKeydown);
        });
    }

    /** The highlighted element of the current step; null when the step has none. */
    setTarget(target: Element | null): void {
        this.target = target;
    }

    /**
     * Brings a new step to the user. When the focus is in the popover, on nothing, or the tour has just started, it
     * moves to `card`, so a screen reader reads the step as a dialog. Otherwise the user is working on the page (e.g.
     * clicked the target, which moved the tour on) and keeps the focus there; the step is announced instead. Never
     * both, which would read the step twice.
     */
    presentStep(card: { focusCard(): void }, announcement: string, isFirstStep: boolean): void {
        const focused = this.document.activeElement;
        const isFocusOnPage = focused !== null && focused !== this.document.body && !this.isInPopover(focused);
        if (isFirstStep || !isFocusOnPage) {
            card.focusCard();
        } else if (announcement) {
            void this.liveAnnouncer.announce(announcement, 'polite');
        }
    }

    isFocusInPopover(): boolean {
        const focused = this.document.activeElement;
        return focused !== null && this.isInPopover(focused);
    }

    /** Idempotent. */
    dispose(): void {
        this.popover?.removeEventListener('keydown', this.onPopoverKeydown);
        this.document.removeEventListener('keydown', this.onDocumentKeydown);
        this.popover = null;
        this.target = null;
    }

    private moveFocus(event: KeyboardEvent): void {
        const cycle = [...this.tabbablesIn(this.popover), ...this.tabbablesIn(this.target)];
        if (cycle.length === 0) {
            return;
        }
        const current = cycle.findIndex((element) => element === event.target);
        let next: number;
        if (current !== -1) {
            next = (current + (event.shiftKey ? -1 : 1) + cycle.length) % cycle.length;
        } else {
            // Not a stop itself (e.g. the card, focused at step start): Tab goes to the first stop, Shift+Tab the last.
            next = event.shiftKey ? cycle.length - 1 : 0;
        }
        event.preventDefault();
        cycle[next].focus();
    }

    /** Tab stops in DOM order, `root` included. Positive tabindex order is not honoured. */
    private tabbablesIn(root: Element | null): HTMLElement[] {
        if (!root) {
            return [];
        }
        const candidates = [root, ...Array.from(root.querySelectorAll('*'))];
        return candidates.filter(
            (element): element is HTMLElement =>
                element instanceof HTMLElement &&
                !element.closest('[inert]') &&
                this.interactivityChecker.isFocusable(element) &&
                this.interactivityChecker.isTabbable(element)
        );
    }

    private isInPopover(node: Node): boolean {
        return !!this.popover?.contains(node);
    }

    private isInTarget(node: Node): boolean {
        return !!this.target?.contains(node);
    }
}
