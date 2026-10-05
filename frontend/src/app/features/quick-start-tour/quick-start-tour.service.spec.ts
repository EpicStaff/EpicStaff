import { DOCUMENT } from '@angular/common';
import { signal } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { GetMeResponse } from '@shared/models';
import type { Config, Driver, DriverHook, DriveStep, PopoverDOM } from 'driver.js';
import { Observable, of, Subject, throwError } from 'rxjs';

import { PermissionsService } from '../../services/auth/permissions.service';
import { ProfileService } from '../../services/auth/profile.service';
import { ConfigureModelsDialogService } from '../configure-models/services/configure-models-dialog.service';
import { QUICK_START_TOUR_FACTORY, QuickStartTourService } from './quick-start-tour.service';
import {
    QUICK_START_RESULT_STATUS_ATTRIBUTE,
    QUICK_START_TOUR_ANCHORS,
    QuickStartResultStatus,
    QuickStartTourAnchor,
    tourAnchor,
} from './quick-start-tour-anchors';

type HookOptions = Parameters<DriverHook>[2];

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
    let dialogClosed: Subject<void>;
    let dialogService: { open: ReturnType<typeof vi.fn>; close: ReturnType<typeof vi.fn> };
    let createdTours: FakeDriver[];
    let createTour: ReturnType<typeof vi.fn>;
    let firesOnDestroyed: boolean;

    beforeEach(() => {
        currentUser = signal<GetMeResponse | null>(null);
        markQuickStartTourCompleted = vi.fn(() => of(userWith(1, true)));
        isPermitted = signal(true);
        dialogClosed = new Subject<void>();
        const dialogRef = { closed: dialogClosed };
        dialogService = { open: vi.fn(() => dialogRef), close: vi.fn(() => dialogClosed.next()) };
        createdTours = [];
        firesOnDestroyed = true;
        createTour = vi.fn((config: Config) => {
            const tour = new FakeDriver(config, firesOnDestroyed);
            createdTours.push(tour);
            return Promise.resolve(tour as unknown as Driver);
        });

        TestBed.configureTestingModule({
            providers: [
                {
                    provide: ProfileService,
                    useValue: { currentUserSignal: currentUser, markQuickStartTourCompleted },
                },
                {
                    provide: PermissionsService,
                    useValue: {
                        canOpenConfigureModelsDialog: () => isPermitted(),
                        canApplyQuickstart: () => isPermitted(),
                    },
                },
                { provide: ConfigureModelsDialogService, useValue: dialogService },
                { provide: QUICK_START_TOUR_FACTORY, useValue: createTour },
            ],
        });
        service = TestBed.inject(QuickStartTourService);
    });

    // The step hooks raise a real top-layer host in the shared jsdom document; stop() removes it.
    afterEach(() => service.stop());

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

        it('ends the tour as skipped when the user closes Settings (e.g. Esc)', async () => {
            await service.start();
            const tour = createdTours[0];
            const settingsStep = tour.stepFor(QUICK_START_TOUR_ANCHORS.sidenavSettings);
            tour.run(settingsStep.popover?.onNextClick, settingsStep);

            dialogClosed.next();

            expect(tour.destroy).toHaveBeenCalled();
            expect(markQuickStartTourCompleted).toHaveBeenCalledTimes(1);
        });

        it('keeps the tour running when it closes Settings itself (Back from the Quickstart tab)', async () => {
            await service.start();
            const tour = createdTours[0];
            const settingsStep = tour.stepFor(QUICK_START_TOUR_ANCHORS.sidenavSettings);
            const tabStep = tour.stepFor(QUICK_START_TOUR_ANCHORS.quickstartTab);
            tour.run(settingsStep.popover?.onNextClick, settingsStep);

            tour.run(tabStep.popover?.onPrevClick, tabStep);

            expect(dialogService.close).toHaveBeenCalled();
            expect(tour.movePrevious).toHaveBeenCalled();
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
    });

    describe('steps', () => {
        it('opens Settings and advances when the Settings step moves on (Next or a click on the icon)', async () => {
            await service.start();
            const tour = createdTours[0];
            const settingsStep = tour.stepFor(QUICK_START_TOUR_ANCHORS.sidenavSettings);

            expect(settingsStep.advanceOnClick).toBe(true);
            tour.run(settingsStep.popover?.onNextClick, settingsStep);

            expect(dialogService.open).toHaveBeenCalled();
            expect(tour.moveNext).toHaveBeenCalled();
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

    describe('edge cases', () => {
        it('watches Settings once when both the sidenav click and Next open it, and records one close', async () => {
            const subscribeToClosed = vi.spyOn(dialogClosed, 'subscribe');
            await service.start();
            const tour = createdTours[0];
            const settingsStep = tour.stepFor(QUICK_START_TOUR_ANCHORS.sidenavSettings);

            tour.run(settingsStep.popover?.onNextClick, settingsStep);
            tour.run(settingsStep.popover?.onNextClick, settingsStep);
            dialogClosed.next();

            expect(subscribeToClosed).toHaveBeenCalledTimes(1);
            expect(markQuickStartTourCompleted).toHaveBeenCalledTimes(1);
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
