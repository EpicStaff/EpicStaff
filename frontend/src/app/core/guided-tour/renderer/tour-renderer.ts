import { EnvironmentInjector, inject, InjectionToken } from '@angular/core';
import { Observable } from 'rxjs';

import { TourContent, TourFloatingPosition, TourSide } from '../model/tour-content';

/**
 * What the user asked for: a popover button, or Escape (`escape`). A renderer reports every one, whatever the step
 * shows; the tour alone decides what it means (Escape ends a tour only if the tour allows it and the step shows the
 * close button; Next and Back do nothing while the step is pending).
 */
export type TourIntent = 'next' | 'back' | 'skip' | 'close' | 'escape';

/** A label shows the button; `false` hides it. */
export interface TourStepButtons {
    readonly next: string | false;
    readonly back: string | false;
    readonly skip: string | false;
    readonly close: boolean;
}

export interface TourProgress {
    /** 1-based. */
    readonly current: number;
    readonly total: number;
}

/** Everything a renderer needs to show one step. Built by the tour; the renderer keeps no step state of its own. */
export interface TourStepView {
    readonly content: TourContent;
    /** Null, or not visible when shown: the popover floats at `floating` and nothing is highlighted. */
    readonly target: Element | null;
    readonly side: TourSide;
    readonly floating: TourFloatingPosition;
    readonly buttons: TourStepButtons;
    readonly progress: TourProgress | null;
}

/**
 * Draws a tour on screen. Tour definitions talk to this interface only, so the drawing (today the CDK renderer) can
 * change without touching them. How a step is presented (placement, stacking, focus, what a screen reader hears) is
 * the renderer's business.
 */
export interface TourRenderer {
    /** Emits in the Angular zone. Completes on dispose. */
    readonly intents: Observable<TourIntent>;
    /** Shows a step, replacing the current one. The new step is not pending. */
    show(view: TourStepView): void;
    /**
     * Whether the step on screen is pending: the tour has moved on from it and waits to show the next one (for its
     * target, or for a dialog to close). Next and Back then do nothing, and must look like it.
     */
    setPending(isPending: boolean): void;
    /** Removes the tour. Idempotent; a disposed renderer ignores every other call. */
    dispose(): void;
}

export type TourRendererLoader = () => Promise<TourRenderer>;

/** Creates a renderer per tour. Lazy, so no renderer code is in the initial bundle; a token, so specs can fake it. */
export const TOUR_RENDERER_LOADER = new InjectionToken<TourRendererLoader>('TOUR_RENDERER_LOADER', {
    providedIn: 'root',
    factory: () => {
        const injector = inject(EnvironmentInjector);
        return async () => {
            const { createCdkTourRenderer } = await import('./cdk/cdk-tour-renderer');
            return createCdkTourRenderer(injector);
        };
    },
});
