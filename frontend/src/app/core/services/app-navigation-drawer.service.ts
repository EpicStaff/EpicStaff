import { inject, Injectable, Injector, signal } from '@angular/core';
import { Router } from '@angular/router';
import { afterNavigationRender } from '@shared/utils';

/**
 * Route data key. On a phone, a page under a route that carries it (anywhere in the active route tree) gets the whole
 * width: the app navigation leaves the layout and opens over the page on demand, through `AppNavigationDrawerService`.
 */
export const HIDE_SIDENAV_ON_PHONE = 'hideSidenavOnPhone';

/**
 * Whether the app navigation is open over the page, on the pages that hide it on phones (`HIDE_SIDENAV_ON_PHONE`). A
 * feature opens it from a button of its own; the main layout shows it and closes it on a backdrop tap, Escape and every
 * navigation. In `core`, so features reach it without depending on the layout.
 */
@Injectable({ providedIn: 'root' })
export class AppNavigationDrawerService {
    private readonly isOpenSignal = signal(false);
    readonly isOpen = this.isOpenSignal.asReadonly();

    private readonly injector = inject(Injector);
    private readonly router = inject(Router);
    // Gets the focus back on close, if it is still on the page then (a navigation may have replaced it).
    private returnFocusTo: HTMLElement | null = null;

    /** `returnFocusTo`: the control the user opened it from, or the one that stands for it once that one is gone. */
    open(returnFocusTo: HTMLElement | null): void {
        this.returnFocusTo = returnFocusTo;
        this.isOpenSignal.set(true);
    }

    close(): void {
        if (!this.isOpenSignal()) return;
        this.isOpenSignal.set(false);
        const target = this.returnFocusTo;
        this.returnFocusTo = null;
        // After the render that hands the page its interactivity back (an inert page cannot take the focus), and after a
        // navigation in progress: a link followed in it may leave the page the control was on.
        if (target) afterNavigationRender(this.router, this.injector, () => target.isConnected && target.focus());
    }
}
