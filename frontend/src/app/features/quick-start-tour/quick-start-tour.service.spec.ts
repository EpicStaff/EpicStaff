import { DOCUMENT } from '@angular/common';
import { provideLocationMocks } from '@angular/common/testing';
import { signal } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { provideRouter, Router, Routes } from '@angular/router';
import { GetMeResponse } from '@shared/models';
import type { Config, Driver, DriverHook, DriveStep, PopoverDOM } from 'driver.js';
import { Observable, of, Subject, take, tap, throwError } from 'rxjs';

import { SETTINGS_QUICKSTART_URL, SETTINGS_URL, settingsIndexGuard } from '../../core/guards/settings.guard';
import { PermissionsService } from '../../services/auth/permissions.service';
import { ProfileService } from '../../services/auth/profile.service';
import { QUICK_START_TOUR_FACTORY, QuickStartTourService } from './quick-start-tour.service';
import {
    QUICK_START_RESULT_STATUS_ATTRIBUTE,
    QUICK_START_TOUR_ANCHORS,
    QuickStartResultStatus,
    QuickStartTourAnchor,
    tourAnchor,
} from './quick-start-tour-anchors';

type HookOptions = Parameters<DriverHook>[2];

/** A page with unsaved changes; leaving it runs a canDeactivate guard, like UnsavedChangesGuard on the real pages. */
const EDITOR_URL = '/editor';
/** A page whose canActivate is still checking: a navigation to it stays in flight until a test answers. */
const SLOW_PAGE_URL = '/slow-page';

interface RouteGuards {
    canLeaveEditor: () => Observable<boolean>;
    canEnterSlowPage: () => Observable<boolean>;
}

/** The Settings routes the tour depends on (the index redirects through the real guard), plus guarded pages. */
function createRoutes({ canLeaveEditor, canEnterSlowPage }: RouteGuards): Routes {
    return [
        {
            path: 'settings',
            children: [
                { path: '', pathMatch: 'full', canActivate: [settingsIndexGuard], children: [] },
                { path: 'quickstart', children: [] },
                { path: 'secrets', children: [] },
            ],
        },
        { path: 'editor', canDeactivate: [() => canLeaveEditor()], children: [] },
        { path: 'slow-page', canActivate: [() => canEnterSlowPage()], children: [] },
        { path: '**', children: [] },
    ];
}

/**
 * Minimal stand-in for a driver.js Driver. Like driver.js, `destroy()` runs the highlighted step's `onDeselected`
 * (`run(step.onHighlighted, step)` marks a step highlighted). `firesOnDestroyed: false` mimics driver.js skipping
 * `onDestroyed` when the tour is destroyed before its first highlight finished animating.
 */
class FakeDriver {
    readonly drive = vi.fn(() => (this.active = true));
    readonly moveNext = vi.fn();
    readonly movePrevious = vi.fn();
    readonly moveTo = vi.fn();
    readonly destroy = vi.fn(() => {
        this.active = false;
        const highlighted = this.highlighted;
        this.highlighted = null;
        if (highlighted) {
            highlighted.step.onDeselected?.(highlighted.element, highlighted.step, this.hookOptions());
        }
        if (this.firesOnDestroyed) {
            this.config.onDestroyed?.(undefined, {}, this.hookOptions());
        }
    });
    private active = false;
    private highlighted: { step: DriveStep; element: Element | undefined } | null = null;

    constructor(
        readonly config: Config,
        private readonly firesOnDestroyed: boolean
    ) {}

    isActive(): boolean {
        return this.active;
    }

    hookOptions(): HookOptions {
        return { config: this.config, state: {}, driver: this as unknown as Driver, index: undefined };
    }

    stepFor(anchor: QuickStartTourAnchor): DriveStep {
        const step = this.config.steps?.find((candidate) => candidate.element === tourAnchor(anchor));
        if (!step) {
            throw new Error(`no step for ${anchor}`);
        }
        return step;
    }

    run(hook: DriverHook | undefined, step: DriveStep, element?: Element): void {
        if (hook && hook === step.onHighlighted) {
            this.highlighted = { step, element };
        }
        hook?.(element, step, this.hookOptions());
    }
}

function userWith(id: number, quickstartTourCompleted: boolean): GetMeResponse {
    return { id, email: `user${id}@example.com`, quickstart_tour_completed: quickstartTourCompleted } as GetMeResponse;
}

describe('QuickStartTourService', () => {
    let service: QuickStartTourService;
    let currentUser: ReturnType<typeof signal<GetMeResponse | null>>;
    let markQuickStartTourCompleted: ReturnType<typeof vi.fn<() => Observable<GetMeResponse>>>;
    let isPermitted: ReturnType<typeof signal<boolean>>;
    let router: Router;
    let editorHasUnsavedChanges: boolean;
    /** The user's answer in the unsaved-changes dialog: true leaves, false stays. Pending until a test answers. */
    let leaveEditorAnswer: Subject<boolean>;
    /** The unsaved-changes dialog. */
    let askToLeaveEditor: ReturnType<typeof vi.fn<() => Observable<boolean>>>;
    /** The slow page's canActivate answer; pending until a test answers. */
    let slowPageAccess: Subject<boolean>;
    let canEnterSlowPage: ReturnType<typeof vi.fn<() => Observable<boolean>>>;
    let createdTours: FakeDriver[];
    let createTour: ReturnType<typeof vi.fn>;
    let firesOnDestroyed: boolean;

    beforeEach(() => {
        currentUser = signal<GetMeResponse | null>(null);
        markQuickStartTourCompleted = vi.fn(() => of(userWith(1, true)));
        isPermitted = signal(true);
        editorHasUnsavedChanges = true;
        leaveEditorAnswer = new Subject<boolean>();
        askToLeaveEditor = vi.fn(() => leaveEditorAnswer.pipe(take(1)));
        slowPageAccess = new Subject<boolean>();
        canEnterSlowPage = vi.fn(() => slowPageAccess.pipe(take(1)));
        createdTours = [];
        firesOnDestroyed = true;
        createTour = vi.fn((config: Config) => {
            const tour = new FakeDriver(config, firesOnDestroyed);
            createdTours.push(tour);
            return Promise.resolve(tour as unknown as Driver);
        });

        TestBed.configureTestingModule({
            providers: [
                provideRouter(createRoutes({ canLeaveEditor, canEnterSlowPage: () => canEnterSlowPage() })),
                provideLocationMocks(),
                {
                    provide: ProfileService,
                    useValue: { currentUserSignal: currentUser, markQuickStartTourCompleted },
                },
                {
                    provide: PermissionsService,
                    useValue: {
                        can: () => isPermitted(),
                        canOpenConfigureModelsDialog: () => isPermitted(),
                        canApplyQuickstart: () => isPermitted(),
                    },
                },
                { provide: QUICK_START_TOUR_FACTORY, useValue: createTour },
            ],
        });
        service = TestBed.inject(QuickStartTourService);
        router = TestBed.inject(Router);
    });

    // The step hooks raise a real top-layer host in the shared jsdom document; stop() removes it.
    afterEach(() => service.stop());

    async function routerSettled(): Promise<void> {
        await vi.waitFor(() => expect(router.currentNavigation()).toBeNull());
    }

    /** Waits until the router has settled on the Quickstart settings tab (a guard redirect is a second navigation). */
    async function expectOnQuickstartTab(): Promise<void> {
        await routerSettled();
        expect(router.url).toBe(SETTINGS_QUICKSTART_URL);
    }

    function runSettingsStepNext(tour: FakeDriver): void {
        const settingsStep = tour.stepFor(QUICK_START_TOUR_ANCHORS.sidenavSettings);
        tour.run(settingsStep.popover?.onNextClick, settingsStep);
    }

    /** Runs the Settings step's Next and waits for the tab. */
    async function openSettingsFromTour(tour: FakeDriver): Promise<void> {
        runSettingsStepNext(tour);
        await expectOnQuickstartTab();
    }

    /**
     * Like the real pages' canDeactivate (via UnsavedChangesGuard): asks the user while there are unsaved changes; once
     * the user chose to leave, the changes are discarded and the page lets go without asking. That matters because the
     * /settings index redirect is a second navigation, which asks the page again.
     */
    function canLeaveEditor(): Observable<boolean> {
        if (!editorHasUnsavedChanges) {
            return of(true);
        }
        return askToLeaveEditor().pipe(tap((isLeaving) => (editorHasUnsavedChanges = !isLeaving)));
    }

    /**
     * Runs the Settings step from the page with unsaved changes, until the user is asked about them. `icon` is a click
     * on the Settings icon in the order a browser runs it: the icon's router link starts its navigation, the router
     * gets as far as it can (to the unsaved-changes dialog), and only then does driver.js's document click listener run
     * the step's Next. `Next` is the popover's button.
     */
    async function leaveEditorForSettings(tour: FakeDriver, trigger: 'icon' | 'Next'): Promise<void> {
        const timesAsked = askToLeaveEditor.mock.calls.length;
        if (trigger === 'icon') {
            void router.navigateByUrl(SETTINGS_URL);
            await vi.waitFor(() => expect(askToLeaveEditor).toHaveBeenCalledTimes(timesAsked + 1));
            runSettingsStepNext(tour);
        } else {
            runSettingsStepNext(tour);
            await vi.waitFor(() => expect(askToLeaveEditor).toHaveBeenCalledTimes(timesAsked + 1));
        }
    }

    describe('startIfNotCompleted', () => {
        it('does not start the tour for a user who already completed it', async () => {
            currentUser.set(userWith(1, true));

            service.startIfNotCompleted();
            await Promise.resolve();

            expect(createTour).not.toHaveBeenCalled();
        });

        it('starts the tour once for a user who has not completed it', async () => {
            currentUser.set(userWith(1, false));

            service.startIfNotCompleted();
            service.startIfNotCompleted();
            await vi.waitFor(() => expect(createdTours[0]?.drive).toHaveBeenCalled());
            service.startIfNotCompleted();

            expect(createTour).toHaveBeenCalledTimes(1);
        });

        it('waits until the user is loaded', async () => {
            service.startIfNotCompleted();
            expect(createTour).not.toHaveBeenCalled();

            currentUser.set(userWith(1, false));
            service.startIfNotCompleted();

            await vi.waitFor(() => expect(createTour).toHaveBeenCalledTimes(1));
        });

        it('does not start without permission, but does once the permission arrives (org switch)', async () => {
            isPermitted.set(false);
            currentUser.set(userWith(1, false));

            service.startIfNotCompleted();
            await Promise.resolve();
            expect(createTour).not.toHaveBeenCalled();

            isPermitted.set(true);
            service.startIfNotCompleted();

            await vi.waitFor(() => expect(createTour).toHaveBeenCalledTimes(1));
        });

        it('re-arms after sign-out: signing back in without completing it starts it again', async () => {
            currentUser.set(userWith(1, false));
            service.startIfNotCompleted();
            await vi.waitFor(() => expect(createTour).toHaveBeenCalledTimes(1));
            service.stop();

            currentUser.set(null);
            TestBed.tick();
            currentUser.set(userWith(1, false));
            service.startIfNotCompleted();

            await vi.waitFor(() => expect(createTour).toHaveBeenCalledTimes(2));
        });
    });

    describe('start', () => {
        it('starts even when the tour was already completed (manual start)', async () => {
            currentUser.set(userWith(1, true));

            await service.start();

            expect(createdTours[0].drive).toHaveBeenCalled();
        });

        it('does not start manually without permission', async () => {
            isPermitted.set(false);

            await service.start();

            expect(createTour).not.toHaveBeenCalled();
        });

        it('ignores a second start while a tour is starting or running', async () => {
            await Promise.all([service.start(), service.start()]);
            await service.start();

            expect(createTour).toHaveBeenCalledTimes(1);
        });

        it('logs and recovers when the tour cannot be created', async () => {
            const consoleError = vi.spyOn(console, 'error').mockImplementation(() => undefined);
            createTour.mockReturnValueOnce(Promise.reject(new Error('chunk load failed')));

            await service.start();
            expect(consoleError).toHaveBeenCalled();
            consoleError.mockRestore();

            await service.start();
            expect(createdTours[0].drive).toHaveBeenCalled();
        });

        it('does not throw when saving the completion fails', async () => {
            const consoleError = vi.spyOn(console, 'error').mockImplementation(() => undefined);
            markQuickStartTourCompleted.mockReturnValue(throwError(() => new Error('network')));
            await service.start();
            const tour = createdTours[0];

            expect(() => tour.run(tour.config.onCloseClick, {})).not.toThrow();
            expect(consoleError).toHaveBeenCalled();
            consoleError.mockRestore();
        });

        it('disables keyboard navigation and closing on overlay clicks', async () => {
            await service.start();
            const { config } = createdTours[0];

            expect(config.allowKeyboardControl).toBe(false);
            expect(typeof config.overlayClickBehavior).toBe('function');
        });
    });

    describe('exits', () => {
        it.each([true, false])(
            'records Skip on the welcome step once and ends the tour (onDestroyed fires: %s)',
            async (destroyFiresOnDestroyed) => {
                firesOnDestroyed = destroyFiresOnDestroyed;
                await service.start();
                const tour = createdTours[0];
                const welcomeStep = tour.config.steps![0];

                tour.run(welcomeStep.popover?.onPrevClick, welcomeStep);

                expect(tour.destroy).toHaveBeenCalled();
                expect(markQuickStartTourCompleted).toHaveBeenCalledTimes(1);
            }
        );

        it('records the close button even when driver.js skips onDestroyed, and can start again', async () => {
            firesOnDestroyed = false;
            await service.start();
            const tour = createdTours[0];

            tour.run(tour.config.onCloseClick, {});
            await service.start();

            expect(markQuickStartTourCompleted).toHaveBeenCalledTimes(1);
            expect(createTour).toHaveBeenCalledTimes(2);
        });

        it('records Finish on the last step', async () => {
            await service.start();
            const tour = createdTours[0];
            const doneStep = tour.stepFor(QUICK_START_TOUR_ANCHORS.quickstartResult);

            tour.run(doneStep.popover?.onNextClick, doneStep);

            expect(tour.destroy).toHaveBeenCalled();
            expect(markQuickStartTourCompleted).toHaveBeenCalledTimes(1);
        });

        it.each([
            ['another page', '/agents'],
            ['another Settings tab', '/settings/secrets'],
        ])('ends the tour as skipped when the user leaves the Quickstart tab for %s', async (_target, url) => {
            await service.start();
            const tour = createdTours[0];
            await openSettingsFromTour(tour);

            await router.navigateByUrl(url);

            expect(tour.destroy).toHaveBeenCalledTimes(1);
            expect(markQuickStartTourCompleted).toHaveBeenCalledTimes(1);
        });

        it('keeps the tour running, and stays on Settings, on Back from the Quickstart tab', async () => {
            await service.start();
            const tour = createdTours[0];
            const tabStep = tour.stepFor(QUICK_START_TOUR_ANCHORS.quickstartTab);
            await openSettingsFromTour(tour);

            tour.run(tabStep.popover?.onPrevClick, tabStep);
            await expectOnQuickstartTab();

            expect(tour.movePrevious).toHaveBeenCalled();
            // Back to the Settings icon: leaving Settings from there no longer ends the tour.
            await router.navigateByUrl('/agents');
            expect(tour.destroy).not.toHaveBeenCalled();
            expect(markQuickStartTourCompleted).not.toHaveBeenCalled();
        });

        it('does not start, and leaves no layer behind, when stopped while driver.js is loading', async () => {
            let resolveTour: (tour: Driver) => void = () => undefined;
            createTour.mockImplementationOnce((config: Config) => {
                const tour = new FakeDriver(config, true);
                createdTours.push(tour);
                return new Promise<Driver>((resolve) => (resolveTour = resolve)).then(() => tour as unknown as Driver);
            });

            const starting = service.start();
            service.stop();
            resolveTour({} as Driver);
            await starting;

            const tour = createdTours[0];
            expect(tour.drive).not.toHaveBeenCalled();
            // A late hook of the abandoned tour must not re-create the host either.
            tour.config.steps![0].popover?.onPopoverRender?.({} as PopoverDOM, tour.hookOptions());
            expect(TestBed.inject(DOCUMENT).querySelector('.quickstart-tour-layer')).toBeNull();
            expect(markQuickStartTourCompleted).not.toHaveBeenCalled();
        });

        it('stop() ends the tour without recording it', async () => {
            await service.start();

            service.stop();

            expect(createdTours[0].destroy).toHaveBeenCalled();
            expect(markQuickStartTourCompleted).not.toHaveBeenCalled();
        });

        // A watcher left over from the previous tour would stop the next one from watching Settings at all.
        it.each<[exit: string, completionsBefore: number, endTour: (tour: FakeDriver) => void]>([
            ['stopped', 0, () => service.stop()],
            ['finished', 1, (tour) => tour.run(tour.config.onCloseClick, {})],
        ])(
            'stops watching Settings once a tour is %s, so the next tour watches it afresh',
            async (_exit, completionsBefore, endTour) => {
                await service.start();
                const firstTour = createdTours[0];
                await openSettingsFromTour(firstTour);
                endTour(firstTour);
                await router.navigateByUrl('/agents');
                expect(firstTour.destroy).toHaveBeenCalledTimes(1);
                expect(markQuickStartTourCompleted).toHaveBeenCalledTimes(completionsBefore);

                await service.start();
                const secondTour = createdTours[1];
                await openSettingsFromTour(secondTour);
                await router.navigateByUrl('/agents');

                expect(secondTour.destroy).toHaveBeenCalledTimes(1);
                expect(markQuickStartTourCompleted).toHaveBeenCalledTimes(completionsBefore + 1);
            }
        );

        it('stop() while waiting for Settings: a navigation that arrives afterwards changes nothing', async () => {
            await router.navigateByUrl(EDITOR_URL);
            await service.start();
            const tour = createdTours[0];
            await leaveEditorForSettings(tour, 'Next');

            service.stop();
            leaveEditorAnswer.next(true);
            await expectOnQuickstartTab();
            await router.navigateByUrl('/agents');

            expect(tour.moveNext).not.toHaveBeenCalled();
            expect(tour.destroy).toHaveBeenCalledTimes(1);
            expect(markQuickStartTourCompleted).not.toHaveBeenCalled();
        });
    });

    describe('steps', () => {
        it('on Next, opens the Quickstart settings tab and moves on only once it is shown', async () => {
            await router.navigateByUrl('/agents');
            await service.start();
            const tour = createdTours[0];
            expect(tour.stepFor(QUICK_START_TOUR_ANCHORS.sidenavSettings).advanceOnClick).toBe(true);

            runSettingsStepNext(tour);
            expect(tour.moveNext).not.toHaveBeenCalled();

            await expectOnQuickstartTab();
            expect(tour.moveNext).toHaveBeenCalledTimes(1);
            // The tour's own navigation is not the user leaving Settings.
            expect(tour.destroy).not.toHaveBeenCalled();
            expect(markQuickStartTourCompleted).not.toHaveBeenCalled();
        });

        it('moves on at once, without navigating, when the Quickstart tab is already shown', async () => {
            await router.navigateByUrl(SETTINGS_QUICKSTART_URL);
            await service.start();
            const tour = createdTours[0];
            const navigateByUrl = vi.spyOn(router, 'navigateByUrl');

            runSettingsStepNext(tour);

            expect(tour.moveNext).toHaveBeenCalledTimes(1);
            expect(navigateByUrl).not.toHaveBeenCalled();
        });

        it('advances the provider steps on the user clicking the highlighted element', async () => {
            await service.start();
            const tour = createdTours[0];

            expect(tour.stepFor(QUICK_START_TOUR_ANCHORS.quickstartProvider).advanceOnClick).toBe(true);
            expect(tour.stepFor(QUICK_START_TOUR_ANCHORS.quickstartProviderList).advanceOnClick).toBe(true);
        });

        it('leaves the Activate step only once the quickstart result is rendered', async () => {
            await service.start();
            const tour = createdTours[0];
            tour.drive();
            const activateStep = tour.stepFor(QUICK_START_TOUR_ANCHORS.quickstartActivate);
            expect(activateStep.advanceOnClick).toBeFalsy();
            expect(activateStep.popover?.showButtons).not.toContain('next');

            tour.run(activateStep.onHighlighted, activateStep);
            await Promise.resolve();
            expect(tour.moveNext).not.toHaveBeenCalled();

            const document = TestBed.inject(DOCUMENT);
            const resultCard = document.createElement('div');
            resultCard.setAttribute('data-tour', QUICK_START_TOUR_ANCHORS.quickstartResult);
            document.body.appendChild(resultCard);

            await vi.waitFor(() => expect(tour.moveNext).toHaveBeenCalledTimes(1));
            resultCard.remove();
        });

        it('stops waiting for the result once the Activate step is left', async () => {
            await service.start();
            const tour = createdTours[0];
            tour.drive();
            const activateStep = tour.stepFor(QUICK_START_TOUR_ANCHORS.quickstartActivate);
            tour.run(activateStep.onHighlighted, activateStep);
            tour.run(activateStep.onDeselected, activateStep);

            const document = TestBed.inject(DOCUMENT);
            const resultCard = document.createElement('div');
            resultCard.setAttribute('data-tour', QUICK_START_TOUR_ANCHORS.quickstartResult);
            document.body.appendChild(resultCard);
            await new Promise((resolve) => setTimeout(resolve, 0));

            expect(tour.moveNext).not.toHaveBeenCalled();
            resultCard.remove();
        });
    });

    // The page the user leaves may ask about unsaved changes (a canDeactivate guard); the tour must not ask twice.
    describe('leaving a page for Settings', () => {
        it('moves on without navigating again when the Settings icon link already got to the tab', async () => {
            await router.navigateByUrl('/agents');
            await service.start();
            const tour = createdTours[0];
            const navigateByUrl = vi.spyOn(router, 'navigateByUrl');

            // A click on the icon: with nothing to ask, the link's navigation (and the index redirect, which the
            // router schedules itself) is done before driver.js's document click listener runs Next.
            void router.navigateByUrl(SETTINGS_URL);
            await routerSettled();
            runSettingsStepNext(tour);

            expect(navigateByUrl).toHaveBeenCalledTimes(1);
            expect(navigateByUrl).toHaveBeenCalledWith(SETTINGS_URL);
            expect(tour.moveNext).toHaveBeenCalledTimes(1);
            expect(tour.destroy).not.toHaveBeenCalled();
            expect(markQuickStartTourCompleted).not.toHaveBeenCalled();
        });

        it.each(['icon', 'Next'] as const)(
            'via the Settings %s: asks the page once and moves on when the user leaves it',
            async (trigger) => {
                await router.navigateByUrl(EDITOR_URL);
                await service.start();
                const tour = createdTours[0];

                await leaveEditorForSettings(tour, trigger);
                expect(tour.moveNext).not.toHaveBeenCalled();
                leaveEditorAnswer.next(true);
                await expectOnQuickstartTab();

                expect(askToLeaveEditor).toHaveBeenCalledTimes(1);
                expect(tour.moveNext).toHaveBeenCalledTimes(1);
                expect(tour.destroy).not.toHaveBeenCalled();
                expect(markQuickStartTourCompleted).not.toHaveBeenCalled();
            }
        );

        it.each(['icon', 'Next'] as const)(
            'via the Settings %s: stays on the Settings step, recording nothing, when the user stays',
            async (trigger) => {
                await router.navigateByUrl(EDITOR_URL);
                await service.start();
                const tour = createdTours[0];

                await leaveEditorForSettings(tour, trigger);
                leaveEditorAnswer.next(false);
                await routerSettled();

                expect(router.url).toBe(EDITOR_URL);
                expect(askToLeaveEditor).toHaveBeenCalledTimes(1);
                expect(tour.moveNext).not.toHaveBeenCalled();
                expect(tour.destroy).not.toHaveBeenCalled();
                expect(markQuickStartTourCompleted).not.toHaveBeenCalled();

                // The user can try again from the same step.
                await leaveEditorForSettings(tour, trigger);
                leaveEditorAnswer.next(true);
                await expectOnQuickstartTab();
                expect(askToLeaveEditor).toHaveBeenCalledTimes(2);
                expect(tour.moveNext).toHaveBeenCalledTimes(1);
            }
        );

        it('ignores a second Next while the navigation to Settings is pending', async () => {
            await router.navigateByUrl(EDITOR_URL);
            await service.start();
            const tour = createdTours[0];
            await leaveEditorForSettings(tour, 'icon');

            runSettingsStepNext(tour);
            leaveEditorAnswer.next(true);
            await expectOnQuickstartTab();

            expect(askToLeaveEditor).toHaveBeenCalledTimes(1);
            expect(tour.moveNext).toHaveBeenCalledTimes(1);
        });

        it('supersedes a navigation in flight elsewhere with its own, and moves on once on the tab', async () => {
            await router.navigateByUrl('/agents');
            await service.start();
            const tour = createdTours[0];
            void router.navigateByUrl(SLOW_PAGE_URL);
            await vi.waitFor(() => expect(canEnterSlowPage).toHaveBeenCalled());
            const navigateByUrl = vi.spyOn(router, 'navigateByUrl');

            runSettingsStepNext(tour);
            await expectOnQuickstartTab();

            expect(navigateByUrl).toHaveBeenCalledExactlyOnceWith(SETTINGS_QUICKSTART_URL);
            expect(tour.moveNext).toHaveBeenCalledTimes(1);
            // The superseded navigation's guard answering late changes nothing.
            slowPageAccess.next(true);
            await routerSettled();
            expect(router.url).toBe(SETTINGS_QUICKSTART_URL);
        });

        // Stands in for a slow network: the navigation is still on its way when the user goes Back.
        it('Back on the Settings step drops a pending navigation: arriving later does not move on', async () => {
            await router.navigateByUrl(EDITOR_URL);
            await service.start();
            const tour = createdTours[0];
            const settingsStep = tour.stepFor(QUICK_START_TOUR_ANCHORS.sidenavSettings);
            await leaveEditorForSettings(tour, 'Next');

            tour.run(settingsStep.popover?.onPrevClick, settingsStep);
            leaveEditorAnswer.next(true);
            await expectOnQuickstartTab();
            await router.navigateByUrl('/agents');

            expect(tour.movePrevious).toHaveBeenCalledTimes(1);
            expect(tour.moveNext).not.toHaveBeenCalled();
            expect(tour.destroy).not.toHaveBeenCalled();
            expect(markQuickStartTourCompleted).not.toHaveBeenCalled();
        });
    });

    describe('edge cases', () => {
        it('does not treat query parameters on the Quickstart tab as leaving it', async () => {
            await service.start();
            const tour = createdTours[0];
            await openSettingsFromTour(tour);

            await router.navigateByUrl(`${SETTINGS_QUICKSTART_URL}?provider=openai#api-key`);

            expect(tour.destroy).not.toHaveBeenCalled();
        });

        it('watches Settings once when it is opened twice, so Back stops all watching', async () => {
            await service.start();
            const tour = createdTours[0];
            const tabStep = tour.stepFor(QUICK_START_TOUR_ANCHORS.quickstartTab);
            await openSettingsFromTour(tour);
            await openSettingsFromTour(tour);

            tour.run(tabStep.popover?.onPrevClick, tabStep);
            await router.navigateByUrl('/agents');

            expect(tour.destroy).not.toHaveBeenCalled();
            expect(markQuickStartTourCompleted).not.toHaveBeenCalled();
        });

        it('does not start a second tour after a successful completion updated the user', async () => {
            markQuickStartTourCompleted.mockImplementation(() => {
                // What ProfileService.setUser does with the POST response.
                currentUser.set(userWith(1, true));
                return of(userWith(1, true));
            });
            currentUser.set(userWith(1, false));
            service.startIfNotCompleted();
            await vi.waitFor(() => expect(createdTours[0]?.drive).toHaveBeenCalled());
            const tour = createdTours[0];

            tour.run(tour.config.onCloseClick, {});
            service.startIfNotCompleted();
            await Promise.resolve();

            expect(createTour).toHaveBeenCalledTimes(1);
        });
    });

    describe('done step', () => {
        let cards: HTMLElement[] = [];
        afterEach(() => {
            cards.forEach((card) => card.remove());
            cards = [];
        });

        function appendResultCard(status: QuickStartResultStatus): { card: HTMLElement; button: HTMLButtonElement } {
            const document = TestBed.inject(DOCUMENT);
            const card = document.createElement('div');
            card.setAttribute('data-tour', QUICK_START_TOUR_ANCHORS.quickstartResult);
            card.setAttribute(QUICK_START_RESULT_STATUS_ATTRIBUTE, status);
            cards.push(card);
            const button = document.createElement('button');
            card.appendChild(button);
            document.body.appendChild(card);
            return { card, button };
        }

        it('finishes the tour before a card button handles the click, and lets the click through', async () => {
            await service.start();
            const tour = createdTours[0];
            const doneStep = tour.stepFor(QUICK_START_TOUR_ANCHORS.quickstartResult);
            const { card, button } = appendResultCard('updated');
            const tourEndedBeforeHandler = vi.fn();
            button.addEventListener('click', () => tourEndedBeforeHandler(tour.destroy.mock.calls.length > 0));
            const removeListener = vi.spyOn(card, 'removeEventListener');
            tour.run(doneStep.onHighlighted, doneStep, card);

            button.click();
            button.click();

            expect(tourEndedBeforeHandler).toHaveBeenNthCalledWith(1, true);
            expect(tourEndedBeforeHandler).toHaveBeenCalledTimes(2);
            // destroy() deselected the step, which removed the capture listener.
            expect(removeListener).toHaveBeenCalledWith('click', expect.any(Function), { capture: true });
            expect(tour.destroy).toHaveBeenCalledTimes(1);
            expect(markQuickStartTourCompleted).toHaveBeenCalledTimes(1);
        });

        it.each([
            ['activated', 'You’re all set'],
            ['updated', 'One more step'],
        ] as const)('shows the copy for the %s result', async (status, expectedTitle) => {
            await service.start();
            const tour = createdTours[0];
            const doneStep = tour.stepFor(QUICK_START_TOUR_ANCHORS.quickstartResult);
            appendResultCard(status);
            const popover = { title: document.createElement('header'), description: document.createElement('div') };

            doneStep.popover?.onPopoverRender?.(popover as unknown as PopoverDOM, tour.hookOptions());

            expect(popover.title.textContent).toBe(expectedTitle);
            expect(popover.description.innerHTML.includes('Update default models')).toBe(status === 'updated');
        });
    });
});
