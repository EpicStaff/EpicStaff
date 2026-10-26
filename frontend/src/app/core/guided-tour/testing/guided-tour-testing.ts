import { Dialog } from '@angular/cdk/dialog';
import { DOCUMENT } from '@angular/common';
import { provideLocationMocks } from '@angular/common/testing';
import {
    createEnvironmentInjector,
    DestroyRef,
    EnvironmentInjector,
    EnvironmentProviders,
    Provider,
    signal,
} from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { provideRouter, Routes } from '@angular/router';
import { Observable, Subject, throwError } from 'rxjs';

import { GuidedTourService } from '../engine/guided-tour.service';
import { TOUR_ANCHOR_ATTRIBUTE } from '../model/tour-anchor';
import { TOUR_PROGRESS_STORE, TourProgressStore } from '../progress/tour-progress-store';
import { TourDefinitionFactory } from '../registry/guided-tour-registry.service';
import { provideGuidedTours } from '../registry/provide-guided-tours';
import { TOUR_RENDERER_LOADER, TourIntent, TourRenderer, TourStepView } from '../renderer/tour-renderer';

/** Stands in for the renderer: keeps what it was asked to show, and lets a spec act on the popover as the user. */
export class FakeTourRenderer implements TourRenderer {
    /** Every step shown, oldest first. */
    readonly views: TourStepView[] = [];
    isDisposed = false;
    /** Whether the step on screen is shown pending (its Next and Back disabled). */
    isPending = false;
    private readonly intentSubject = new Subject<TourIntent>();
    readonly intents: Observable<TourIntent> = this.intentSubject.asObservable();

    /** The step on screen: null before the first one and once disposed. */
    get view(): TourStepView | null {
        return this.isDisposed ? null : (this.views.at(-1) ?? null);
    }

    show(view: TourStepView): void {
        if (!this.isDisposed) {
            this.views.push(view);
            this.isPending = false;
        }
    }

    setPending(isPending: boolean): void {
        if (!this.isDisposed) {
            this.isPending = isPending;
        }
    }

    dispose(): void {
        if (this.isDisposed) {
            return;
        }
        this.isDisposed = true;
        this.intentSubject.complete();
    }

    /** The user presses a popover button, or Escape. */
    press(intent: TourIntent): void {
        this.intentSubject.next(intent);
    }
}

/** Progress kept in memory. `savedTourKeys` is the side effect specs assert on: what would reach the backend. */
export class FakeTourProgressStore implements TourProgressStore {
    readonly userId = signal<number | null>(null);
    readonly completedTourKeys = signal<ReadonlySet<string>>(new Set());
    /** Every key saved, in order, including failed saves and saves still on their way. */
    readonly savedTourKeys: string[] = [];
    /** Makes saves fail, like a network error. */
    failSaves = false;
    private isHoldingSaves = false;
    private readonly heldSaves: (() => void)[] = [];

    signIn(userId: number, completedTourKeys: readonly string[] = []): void {
        this.completedTourKeys.set(new Set(completedTourKeys));
        this.userId.set(userId);
    }

    signOut(): void {
        this.userId.set(null);
        this.completedTourKeys.set(new Set());
    }

    /**
     * Holds saves on their way, like a slow network: their keys are not completed until the returned function is
     * called, which lands them in order.
     */
    holdSaves(): () => void {
        this.isHoldingSaves = true;
        return () => {
            this.isHoldingSaves = false;
            this.heldSaves.splice(0).forEach((land) => land());
        };
    }

    markCompleted(tourKey: string): Observable<void> {
        this.savedTourKeys.push(tourKey);
        if (this.failSaves) {
            return throwError(() => new Error('Saving failed'));
        }
        return new Observable<void>((subscriber) => {
            const land = (): void => {
                this.completedTourKeys.update((keys) => new Set([...keys, tourKey]));
                subscriber.next();
                subscriber.complete();
            };
            if (this.isHoldingSaves) {
                this.heldSaves.push(land);
            } else {
                land();
            }
        });
    }
}

export interface TourAnchorOptions {
    /** Hidden from the user: no box and not visible, like an icon in a closed drawer. */
    readonly hidden?: boolean;
    readonly tagName?: string;
    /** Default: the document body. */
    readonly parent?: Element;
}

export interface GuidedTourTestbedOptions {
    readonly tours: readonly TourDefinitionFactory[];
    readonly routes?: Routes;
    readonly providers?: readonly (Provider | EnvironmentProviders)[];
}

export interface GuidedTourTestbed {
    readonly service: GuidedTourService;
    readonly progressStore: FakeTourProgressStore;
    /** One per tour run that got its renderer, oldest first. */
    readonly renderers: readonly FakeTourRenderer[];
    /** The renderer of the latest run. Throws when no run got one. */
    renderer(): FakeTourRenderer;
    /** Connects an app shell, as the main layout does. Returns its teardown (the shell going away, e.g. sign-out). */
    connectAppShell(): () => void;
    /** Holds renderer loads (a slow lazy chunk) until the returned function is called. */
    holdRendererLoads(): () => void;
    /** Makes the next renderer load fail, like a lazy chunk that could not be fetched. */
    failNextRendererLoad(): void;
    /** Adds an element marked `data-tour="<anchor>"`, laid out unless hidden (jsdom has no layout of its own). */
    appendAnchor(anchor: string, options?: TourAnchorOptions): HTMLElement;
    /** Runs pending effects (auto-start, availability) and lets renderer loads and other promises in flight finish. */
    settle(): Promise<void>;
    /** Stops the active tour, closes dialogs, removes the anchors and disconnects the shells. Call in afterEach. */
    cleanUp(): void;
}

/**
 * Configures TestBed with the given tours, a real router (with `routes`), a FakeTourRenderer per run and an in-memory
 * progress store. Call in beforeEach.
 */
export function setUpGuidedTourTestbed(options: GuidedTourTestbedOptions): GuidedTourTestbed {
    const progressStore = new FakeTourProgressStore();
    const renderers: FakeTourRenderer[] = [];
    const anchors: HTMLElement[] = [];
    const shellTeardowns: (() => void)[] = [];
    let heldLoad: Promise<void> | null = null;
    let failNextLoad = false;

    const loadRenderer = async (): Promise<TourRenderer> => {
        if (failNextLoad) {
            failNextLoad = false;
            throw new Error('Failed to fetch the renderer chunk');
        }
        await heldLoad;
        const renderer = new FakeTourRenderer();
        renderers.push(renderer);
        return renderer;
    };

    TestBed.configureTestingModule({
        providers: [
            provideRouter(options.routes ?? []),
            provideLocationMocks(),
            provideGuidedTours(...options.tours),
            { provide: TOUR_PROGRESS_STORE, useValue: progressStore },
            { provide: TOUR_RENDERER_LOADER, useValue: loadRenderer },
            ...(options.providers ?? []),
        ],
    });
    const service = TestBed.inject(GuidedTourService);

    return {
        service,
        progressStore,
        renderers,
        renderer: () => {
            const renderer = renderers.at(-1);
            if (!renderer) {
                throw new Error('No tour run has a renderer yet.');
            }
            return renderer;
        },
        connectAppShell: () => {
            const shell = createEnvironmentInjector([], TestBed.inject(EnvironmentInjector));
            let isDestroyed = false;
            const teardown = (): void => {
                if (!isDestroyed) {
                    isDestroyed = true;
                    shell.destroy();
                }
            };
            // Before connecting, so a connection the service refuses still leaves no shell behind.
            shellTeardowns.push(teardown);
            service.connectAppShell(shell.get(DestroyRef));
            return teardown;
        },
        holdRendererLoads: () => {
            let release: () => void = () => undefined;
            heldLoad = new Promise<void>((resolve) => (release = resolve));
            return () => {
                heldLoad = null;
                release();
            };
        },
        failNextRendererLoad: () => {
            failNextLoad = true;
        },
        appendAnchor: (anchor, anchorOptions = {}) => {
            const document = TestBed.inject(DOCUMENT);
            const element = document.createElement(anchorOptions.tagName ?? 'div');
            element.setAttribute(TOUR_ANCHOR_ATTRIBUTE, anchor);
            layOut(element, !anchorOptions.hidden);
            (anchorOptions.parent ?? document.body).appendChild(element);
            anchors.push(element);
            return element;
        },
        settle: async () => {
            TestBed.tick();
            await new Promise<void>((resolve) => setTimeout(resolve));
            TestBed.tick();
        },
        cleanUp: () => {
            service.stop();
            TestBed.inject(Dialog).closeAll();
            shellTeardowns.splice(0).forEach((teardown) => teardown());
            anchors.splice(0).forEach((anchor) => anchor.remove());
        },
    };
}

/** Gives `element` the box and visibility jsdom cannot compute. */
function layOut(element: HTMLElement, isVisible: boolean): void {
    const size = isVisible ? 40 : 0;
    Object.assign(element, {
        getBoundingClientRect: () => ({
            x: 0,
            y: 0,
            top: 0,
            left: 0,
            width: size,
            height: size,
            right: size,
            bottom: size,
            toJSON: () => ({}),
        }),
        checkVisibility: () => isVisible,
    });
}
