import { inject, Injectable, Injector, signal } from '@angular/core';
import { Router } from '@angular/router';
import { afterNavigationRender } from '@shared/utils';

/**
 * The desk drawer of the chat area on phones: whether it is open, and the desk switcher that opens it. The desks shell
 * draws the drawer and provides this; the routed page under it opens it from its desk switcher. The page registers
 * that switcher, so the focus returns to whichever switcher is on screen when the drawer closes, also after a desk
 * change replaced the page that had opened it.
 */
@Injectable()
export class DeskDrawerService {
    private readonly isOpenSignal = signal(false);
    readonly isOpen = this.isOpenSignal.asReadonly();

    private readonly injector = inject(Injector);
    private readonly router = inject(Router);
    private switcher: HTMLElement | null = null;

    /** The desk switcher shown now, which the focus returns to. */
    get opener(): HTMLElement | null {
        return this.switcher;
    }

    /** Called by the page once it shows a desk switcher. */
    registerSwitcher(element: HTMLElement): void {
        this.switcher = element;
    }

    /** A page that stops showing one unregisters only its own: the next page may have registered one already. */
    unregisterSwitcher(element: HTMLElement): void {
        if (this.switcher === element) this.switcher = null;
    }

    open(): void {
        this.isOpenSignal.set(true);
    }

    /** `restoreFocus: false` when the focus goes somewhere else on purpose (the app navigation opening). */
    close({ restoreFocus = true }: { restoreFocus?: boolean } = {}): void {
        if (!this.isOpenSignal()) return;
        this.isOpenSignal.set(false);
        // After the render that removes the drawer and hands the page its interactivity back, and after the navigation
        // a pick started: the switcher then is the one of the page the pick led to.
        if (restoreFocus) afterNavigationRender(this.router, this.injector, () => this.switcher?.focus());
    }
}
