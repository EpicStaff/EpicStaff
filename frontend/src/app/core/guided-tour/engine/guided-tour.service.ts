import {
    computed,
    DestroyRef,
    effect,
    EffectRef,
    EnvironmentInjector,
    inject,
    Injectable,
    isDevMode,
    runInInjectionContext,
    signal,
    untracked,
} from '@angular/core';

import { TourDefinition } from '../model/tour-definition';
import { TOUR_PROGRESS_STORE } from '../progress/tour-progress-store';
import { GuidedTourRegistry } from '../registry/guided-tour-registry.service';
import { TOUR_RENDERER_LOADER, TourRenderer } from '../renderer/tour-renderer';
import { findAutoStartTour } from './tour-eligibility';
import { TourRun, TourRunEnd } from './tour-run';

/** A tour from its start until it ends. `run` is set once the renderer has loaded. */
interface TourSession {
    readonly tour: TourDefinition;
    run: TourRun | null;
}

/** The tours launched for one signed-in user, by auto-start or by the user. */
interface LaunchedTours {
    readonly userId: number | null;
    readonly tourKeys: Set<string>;
}

/**
 * Runs the registered tours: one at a time, started by the user or by auto-start, and saves every explicit exit
 * (Finish, Skip, the close button, leaving a step's route scope) as completed.
 */
@Injectable({
    providedIn: 'root',
})
export class GuidedTourService {
    private readonly registry = inject(GuidedTourRegistry);
    private readonly progressStore = inject(TOUR_PROGRESS_STORE);
    private readonly loadRenderer = inject(TOUR_RENDERER_LOADER);
    private readonly injector = inject(EnvironmentInjector);
    private readonly session = signal<TourSession | null>(null);
    /** Auto-start passes over these. Kept here, not per app shell: the decisions outlive a shell, not a sign-in. */
    private launchedTours: LaunchedTours = { userId: null, tourKeys: new Set() };
    private connectedAppShells = 0;
    /** The tours whose `isAvailable` threw, each logged once. */
    private readonly toursWithFailingAvailability = new Set<string>();

    /** The tour starting or running; null while none is. */
    readonly activeTour = computed<TourDefinition | null>(() => this.session()?.tour ?? null);
    /** The tours the user can take now, in registry order (e.g. for the account menu). */
    readonly replayableTours = computed<readonly TourDefinition[]>(() =>
        this.registry.tours.filter((tour) => this.isTourAvailable(tour))
    );

    // Here, not in the app shell: the shell goes away on sign-out, before the next user (or the same one) signs in.
    // Only a signed-in user's decisions are dropped: tours launched while the profile was still loading are kept for
    // the user it loads (see launchedTourKeysOf).
    private readonly rearmAutoStartOnSignOut = effect(() => {
        if (this.progressStore.userId() === null && this.launchedTours.userId !== null) {
            this.launchedTours = { userId: null, tourKeys: new Set() };
        }
    });

    /**
     * Starts the tour `key`, unless a tour is starting or running, or `key` is unknown or unavailable. Resolves once
     * the tour runs (its first step shows when no dialog is open) or did not start. Auto-start does not start the
     * tour again for this user afterwards, even before its completion is saved.
     */
    async start(key: string): Promise<void> {
        const tour = this.registry.find(key);
        if (!tour) {
            console.error(`[GuidedTour] No tour is registered as "${key}".`);
            return;
        }
        if (this.session() || !untracked(() => this.isTourAvailable(tour))) {
            return;
        }
        await this.launch(tour);
    }

    /** Ends the active tour without saving it as completed, e.g. when the app shell goes away on sign-out. */
    stop(): void {
        const session = this.session();
        if (!session) {
            return;
        }
        this.session.set(null);
        session.run?.stop();
    }

    /**
     * Auto-starts tours while the app shell lives, and stops the active tour when it goes away. Tours point into the
     * shell (its navigation, its pages), so they run only within it. One shell at a time: in dev mode a second
     * connection while one is live throws.
     *
     * Auto-start considers the tours in registry order, one at a time, and again whenever the active tour ends. It
     * starts each tour at most once per signed-in user, whichever shell is connected, and never one the user already
     * started in that sign-in. A tour the user cannot take yet is not passed over for good, so an org switch that makes
     * it available still starts it. Signing out re-arms every tour.
     */
    connectAppShell(destroyRef: DestroyRef): void {
        if (this.connectedAppShells > 0 && isDevMode()) {
            throw new Error('[GuidedTour] An app shell is already connected; disconnect it before connecting another.');
        }
        let autoStart: EffectRef | null = null;
        // Before the effect: for a shell that is already gone this throws, and nothing is left running.
        destroyRef.onDestroy(() => {
            this.connectedAppShells--;
            autoStart?.destroy();
            this.stop();
        });
        this.connectedAppShells++;
        autoStart = effect(
            () => {
                const userId = this.progressStore.userId();
                if (userId === null || this.session()) {
                    return;
                }
                const tour = findAutoStartTour(
                    this.registry.tours,
                    this.progressStore.completedTourKeys(),
                    this.launchedTourKeysOf(userId),
                    (candidate) => this.isTourAvailable(candidate)
                );
                if (tour) {
                    untracked(() => void this.launch(tour));
                }
            },
            { injector: this.injector, manualCleanup: true }
        );
    }

    private async launch(tour: TourDefinition): Promise<void> {
        // However the run ends: its completion may still be on its way when auto-start looks again.
        this.launchedTourKeysOf(untracked(() => this.progressStore.userId())).add(tour.key);
        const session: TourSession = { tour, run: null };
        this.session.set(session);
        let renderer: TourRenderer | null = null;
        try {
            const loadedRenderer = await this.loadRenderer();
            renderer = loadedRenderer;
            if (this.session() !== session) {
                // Stopped while the renderer was loading: nothing is on screen yet.
                loadedRenderer.dispose();
                return;
            }
            const run = runInInjectionContext(
                this.injector,
                () => new TourRun(tour, loadedRenderer, (end) => this.onRunEnded(session, end))
            );
            session.run = run;
            run.start();
        } catch (error: unknown) {
            console.error(`[GuidedTour] Failed to start the tour "${tour.key}":`, error);
            if (session.run) {
                session.run.stop();
            } else {
                renderer?.dispose();
            }
            if (this.session() === session) {
                this.session.set(null);
            }
        }
    }

    /**
     * The launched tours of `userId`. Another signed-in user starts afresh; the tours launched before the profile
     * loaded (no user yet) belong to the first user it loads.
     */
    private launchedTourKeysOf(userId: number | null): Set<string> {
        if (this.launchedTours.userId !== userId) {
            const isProfileLoading = this.launchedTours.userId === null;
            this.launchedTours = { userId, tourKeys: isProfileLoading ? this.launchedTours.tourKeys : new Set() };
        }
        return this.launchedTours.tourKeys;
    }

    /**
     * `tour.isAvailable()`, read so that a definition whose check throws counts as unavailable (logged once) instead of
     * breaking the tour list and auto-start for every tour. In dev mode it throws, like the registry's checks.
     */
    private isTourAvailable(tour: TourDefinition): boolean {
        try {
            return tour.isAvailable();
        } catch (error: unknown) {
            if (isDevMode()) {
                throw error;
            }
            if (!this.toursWithFailingAvailability.has(tour.key)) {
                this.toursWithFailingAvailability.add(tour.key);
                console.error(
                    `[GuidedTour] Checking whether tour "${tour.key}" is available failed; it counts as unavailable:`,
                    error
                );
            }
            return false;
        }
    }

    private onRunEnded(session: TourSession, end: TourRunEnd): void {
        if (this.session() === session) {
            this.session.set(null);
        }
        if (end === 'completed') {
            this.saveCompletion(session.tour.key);
        }
    }

    private saveCompletion(tourKey: string): void {
        this.progressStore.markCompleted(tourKey).subscribe({
            // Not worth a toast: the only effect is that an auto-start tour starts again next session.
            error: (error: unknown) =>
                console.error(`[GuidedTour] Failed to save tour "${tourKey}" as completed:`, error),
        });
    }
}
