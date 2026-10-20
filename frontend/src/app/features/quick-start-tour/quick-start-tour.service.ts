import { DOCUMENT } from '@angular/common';
import { computed, effect, inject, Injectable, InjectionToken } from '@angular/core';
import {
    containsTree,
    Event as RouterEvent,
    IsActiveMatchOptions,
    Navigation,
    NavigationCancel,
    NavigationCancellationCode,
    NavigationEnd,
    NavigationError,
    NavigationSkipped,
    Router,
} from '@angular/router';
import type { Config, Driver } from 'driver.js';
import { filter, Subscription, take } from 'rxjs';

import { SETTINGS_QUICKSTART_URL, SETTINGS_URL } from '../../core/guards/settings.guard';
import { PermissionsService } from '../../services/auth/permissions.service';
import { ProfileService } from '../../services/auth/profile.service';
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

/** Only the path decides whether the user is on the Quickstart tab. */
const QUICKSTART_SETTINGS_MATCH: IsActiveMatchOptions = {
    paths: 'exact',
    queryParams: 'ignored',
    matrixParams: 'ignored',
    fragment: 'ignored',
};
/** Any URL under /settings (the index, which redirects, or one of its tabs). */
const SETTINGS_SECTION_MATCH: IsActiveMatchOptions = { ...QUICKSTART_SETTINGS_MATCH, paths: 'subset' };

const TOUR_CONFIG: Config = {
    popoverClass: QUICK_START_TOUR_POPOVER_CLASS,
    nextBtnText: 'Next',
    prevBtnText: 'Back',
    // Arrow keys would skip the steps that wait for the user to open Settings or the dropdown. driver.js has a
    // single switch for arrows and Esc, so Esc goes too; the close button and Skip remain.
    allowKeyboardControl: false,
    // The default ('close') would end — and record as completed — the tour on a stray click on the dimmed area.
    overlayClickBehavior: () => undefined,
    stageRadius: 8,
};

/**
 * Whether `event` ends a navigation for good. A guard redirect (the /settings index) or a superseding navigation also
 * cancels one, but another navigation follows, so those are not the end.
 */
function isNavigationSettled(event: RouterEvent): boolean {
    if (event instanceof NavigationCancel) {
        return (
            event.code !== NavigationCancellationCode.Redirect &&
            event.code !== NavigationCancellationCode.SupersededByNewNavigation
        );
    }
    return event instanceof NavigationEnd || event instanceof NavigationError || event instanceof NavigationSkipped;
}

@Injectable({
    providedIn: 'root',
})
export class QuickStartTourService {
    private readonly document = inject(DOCUMENT);
    private readonly profileService = inject(ProfileService);
    private readonly permissionsService = inject(PermissionsService);
    private readonly router = inject(Router);
    private readonly createTour = inject(QUICK_START_TOUR_FACTORY);

    private activeTour: Driver | null = null;
    private topLayer: TourTopLayer | null = null;
    private isStarting = false;
    /** Auto-start is decided once per signed-in user; signing out re-arms it (another user may sign in). */
    private autoStartHandledForUserId: number | null = null;
    /** Set while the tour waits for a navigation to settle before it moves past the Settings icon; see openSettings. */
    private settingsArrivalSubscription: Subscription | null = null;
    /** Set while leaving the Quickstart settings tab ends the tour; see enterSettings. */
    private settingsLeftSubscription: Subscription | null = null;

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
                openSettings: (onOpened) => this.openSettings(tour, topLayer, onOpened),
                stopWatchingSettings: () => this.stopWatchingSettings(),
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
        this.stopWatchingSettings();
        tour?.destroy();
        this.releaseTopLayer(this.topLayer);
    }

    /** Every explicit exit (Finish, Skip, close button, the user leaving the Quickstart tab) counts as completed. */
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
        this.stopWatchingSettings();
        this.profileService.markQuickStartTourCompleted().subscribe({
            // Not worth a toast: the only effect is that the tour auto-starts again next session.
            error: (error: unknown) => console.error('[QuickStartTour] Failed to save tour completion:', error),
        });
        return true;
    }

    /**
     * Brings the user to the Quickstart settings tab and calls `onOpened` once it is shown (at once if it already is).
     *
     * There is only ever one navigation into Settings. A click on the Settings icon has started its own by the time
     * this runs (the icon's router link handles the click before driver.js's document listener), and it may be waiting
     * on a canDeactivate guard's unsaved-changes dialog. A second navigation would supersede it and ask the guard
     * again, so the tour follows a navigation already heading into Settings. Any other navigation in flight is
     * superseded by the tour's own. If the navigation does not end on the tab (e.g. the user cancelled the
     * unsaved-changes dialog), the tour stays where it is and nothing is recorded.
     */
    private openSettings(tour: Driver, topLayer: TourTopLayer, onOpened: () => void): void {
        if (this.settingsArrivalSubscription) {
            return;
        }
        const navigation = this.router.currentNavigation();
        if (!navigation && this.isQuickstartSettingsUrl(this.router.url)) {
            this.enterSettings(tour, topLayer, onOpened);
            return;
        }
        this.settingsArrivalSubscription = this.router.events
            .pipe(filter(isNavigationSettled), take(1))
            .subscribe(() => {
                this.settingsArrivalSubscription = null;
                if (this.isQuickstartSettingsUrl(this.router.url)) {
                    this.enterSettings(tour, topLayer, onOpened);
                }
            });
        if (!navigation || !this.isHeadingIntoSettings(navigation)) {
            void this.router.navigateByUrl(SETTINGS_QUICKSTART_URL);
        }
    }

    /**
     * The user is on the Quickstart tab. The remaining steps all point inside it, so from now on leaving it (another
     * Settings tab, another page) ends the tour as skipped.
     */
    private enterSettings(tour: Driver, topLayer: TourTopLayer, onOpened: () => void): void {
        this.settingsLeftSubscription ??= this.router.events
            .pipe(
                filter((event): event is NavigationEnd => event instanceof NavigationEnd),
                filter((event) => !this.isQuickstartSettingsUrl(event.urlAfterRedirects))
            )
            .subscribe(() => this.finish(tour, topLayer));
        onOpened();
    }

    /**
     * Stops waiting for Settings and stops ending the tour when the user leaves it (Back to the Settings icon, and
     * every exit). Settings itself stays open.
     */
    private stopWatchingSettings(): void {
        this.settingsArrivalSubscription?.unsubscribe();
        this.settingsArrivalSubscription = null;
        this.settingsLeftSubscription?.unsubscribe();
        this.settingsLeftSubscription = null;
    }

    /** Recognised routes may have redirected (finalUrl); before recognition only the requested URL is known. */
    private isHeadingIntoSettings(navigation: Navigation): boolean {
        return containsTree(
            navigation.finalUrl ?? navigation.extractedUrl,
            this.router.parseUrl(SETTINGS_URL),
            SETTINGS_SECTION_MATCH
        );
    }

    private isQuickstartSettingsUrl(url: string): boolean {
        return containsTree(
            this.router.parseUrl(url),
            this.router.parseUrl(SETTINGS_QUICKSTART_URL),
            QUICKSTART_SETTINGS_MATCH
        );
    }
}
