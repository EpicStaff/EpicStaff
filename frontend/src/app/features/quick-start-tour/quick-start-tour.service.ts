import { DialogRef } from '@angular/cdk/dialog';
import { DOCUMENT } from '@angular/common';
import { computed, effect, inject, Injectable, InjectionToken } from '@angular/core';
import type { Config, Driver } from 'driver.js';
import { Subscription } from 'rxjs';

import { PermissionsService } from '../../services/auth/permissions.service';
import { ProfileService } from '../../services/auth/profile.service';
import { ConfigureModelsDialogService } from '../configure-models/services/configure-models-dialog.service';
import { createQuickStartTourSteps, QUICK_START_TOUR_POPOVER_CLASS } from './quick-start-tour-steps';
import { TourTopLayer, withTopLayer } from './tour-top-layer';

export type QuickStartTourFactory = (config: Config) => Promise<Driver>;

/** Creates the driver.js tour. Lazy import keeps driver.js out of the initial bundle; a token so specs can fake it. */
export const QUICK_START_TOUR_FACTORY = new InjectionToken<QuickStartTourFactory>('QUICK_START_TOUR_FACTORY', {
    providedIn: 'root',
    factory: () => async (config) => {
        const { driver } = await import('driver.js');
        return driver(config);
    },
});

const TOUR_CONFIG: Config = {
    popoverClass: QUICK_START_TOUR_POPOVER_CLASS,
    nextBtnText: 'Next',
    prevBtnText: 'Back',
    // Arrow keys would skip the steps that wait for the user to open the dialog or the dropdown. driver.js has a
    // single switch for arrows and Esc, so Esc goes too; the close button and Skip remain.
    allowKeyboardControl: false,
    // The default ('close') would end — and record as completed — the tour on a stray click on the dimmed area.
    overlayClickBehavior: () => undefined,
    stageRadius: 8,
};

@Injectable({
    providedIn: 'root',
})
export class QuickStartTourService {
    private readonly document = inject(DOCUMENT);
    private readonly profileService = inject(ProfileService);
    private readonly permissionsService = inject(PermissionsService);
    private readonly configureModelsDialogService = inject(ConfigureModelsDialogService);
    private readonly createTour = inject(QUICK_START_TOUR_FACTORY);

    private activeTour: Driver | null = null;
    private topLayer: TourTopLayer | null = null;
    private isStarting = false;
    /** Auto-start is decided once per signed-in user; signing out re-arms it (another user may sign in). */
    private autoStartHandledForUserId: number | null = null;
    private watchedSettingsDialog: DialogRef<void> | null = null;
    private settingsDialogClosedSubscription: Subscription | null = null;

    /** The tour walks Settings → Quickstart → Activate, so it needs every permission those gate on. */
    public readonly isAvailable = computed<boolean>(
        () => this.permissionsService.canOpenConfigureModelsDialog() && this.permissionsService.canApplyQuickstart()
    );

    private readonly resetAutoStartOnSignOut = effect(() => {
        if (!this.profileService.currentUserSignal()) {
            this.autoStartHandledForUserId = null;
        }
    });

    /**
     * Starts the tour once per signed-in user who has not finished or skipped it. Not marked as handled while the
     * user lacks the permissions, so an org switch that grants them still starts it.
     */
    public startIfNotCompleted(): void {
        const user = this.profileService.currentUserSignal();
        if (!user || this.autoStartHandledForUserId === user.id) {
            return;
        }
        if (user.quickstart_tour_completed) {
            this.autoStartHandledForUserId = user.id;
            return;
        }
        if (!this.isAvailable()) {
            return;
        }
        this.autoStartHandledForUserId = user.id;
        void this.start();
    }

    /** Starts the tour regardless of the completion flag (manual start from the account menu). */
    public async start(): Promise<void> {
        if (this.isStarting || this.activeTour?.isActive() || !this.isAvailable()) {
            return;
        }
        this.isStarting = true;

        // Each tour owns its layer; this.topLayer only marks the one currently starting or running, so stop() can
        // reach it while createTour() is still loading.
        this.releaseTopLayer(this.topLayer);
        const topLayer = new TourTopLayer(this.document);
        this.topLayer = topLayer;

        try {
            const steps = createQuickStartTourSteps({
                document: this.document,
                openSettingsDialog: () => this.openSettingsDialog(tour, topLayer),
                closeSettingsDialog: () => this.closeSettingsDialog(),
                finishTour: () => this.finish(tour, topLayer),
                mountInTourLayer: (element) => topLayer.append(element),
            });
            const tour: Driver = await this.createTour({
                ...TOUR_CONFIG,
                steps: withTopLayer(steps, topLayer),
                onCloseClick: () => this.finish(tour, topLayer),
                // Safety net for exits driver.js takes on its own. Not the primary path: driver.js skips this hook
                // when the tour is destroyed before its first highlight has finished animating.
                onDestroyed: () => {
                    this.recordCompletion(tour);
                    this.releaseTopLayer(topLayer);
                },
            });

            // stop() ran while driver.js was loading (e.g. sign-out): the tour was never driven, so there is nothing
            // on screen to tear down — just don't start it.
            if (this.topLayer !== topLayer) {
                return;
            }
            this.activeTour = tour;
            tour.drive();
        } catch (error: unknown) {
            this.activeTour = null;
            this.releaseTopLayer(topLayer);
            console.error('[QuickStartTour] Failed to start the tour:', error);
        } finally {
            this.isStarting = false;
        }
    }

    /** Ends the tour without recording it as completed — for when the app shell goes away (e.g. sign-out). */
    public stop(): void {
        const tour = this.activeTour;
        this.activeTour = null;
        this.stopWatchingSettingsDialog();
        tour?.destroy();
        this.releaseTopLayer(this.topLayer);
    }

    /** Every explicit exit (Finish, Skip, close button, Settings closed by the user) counts as completed. */
    private finish(tour: Driver, topLayer: TourTopLayer): void {
        if (this.recordCompletion(tour)) {
            tour.destroy();
            this.releaseTopLayer(topLayer);
        }
    }

    /** Disposes a tour's own layer, and forgets it if it is the current one. */
    private releaseTopLayer(topLayer: TourTopLayer | null): void {
        topLayer?.dispose();
        if (this.topLayer === topLayer) {
            this.topLayer = null;
        }
    }

    /** Idempotent: returns false when this tour was already finished or stopped. */
    private recordCompletion(tour: Driver): boolean {
        if (this.activeTour !== tour) {
            return false;
        }
        this.activeTour = null;
        this.stopWatchingSettingsDialog();
        this.profileService.markQuickStartTourCompleted().subscribe({
            // Not worth a toast: the only effect is that the tour auto-starts again next session.
            error: (error: unknown) => console.error('[QuickStartTour] Failed to save tour completion:', error),
        });
        return true;
    }

    /**
     * Opens Settings and watches it: the remaining steps all point inside the dialog, so if the user closes it
     * (Esc, close icon) the tour cannot continue and ends as skipped.
     */
    private openSettingsDialog(tour: Driver, topLayer: TourTopLayer): void {
        const dialogRef = this.configureModelsDialogService.open();
        if (this.watchedSettingsDialog === dialogRef) {
            return;
        }
        this.stopWatchingSettingsDialog();
        this.watchedSettingsDialog = dialogRef;
        this.settingsDialogClosedSubscription = dialogRef.closed.subscribe(() => this.finish(tour, topLayer));
    }

    /** The tour's own close (Back to the Settings step) must not end the tour, so stop watching first. */
    private closeSettingsDialog(): void {
        this.stopWatchingSettingsDialog();
        this.configureModelsDialogService.close();
    }

    private stopWatchingSettingsDialog(): void {
        this.settingsDialogClosedSubscription?.unsubscribe();
        this.settingsDialogClosedSubscription = null;
        this.watchedSettingsDialog = null;
    }
}
