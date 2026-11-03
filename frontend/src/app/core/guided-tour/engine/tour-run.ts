import { Dialog } from '@angular/cdk/dialog';
import { DOCUMENT } from '@angular/common';
import { inject } from '@angular/core';
import { map, Observable, Observer, Subscription, switchMap, take } from 'rxjs';

import { TourContent, TourFloatingPosition, TourSide } from '../model/tour-content';
import { TourContentContext, TourDefinition, TourNavigationAdvance, TourStep } from '../model/tour-definition';
import { TourIntent, TourProgress, TourRenderer, TourStepButtons } from '../renderer/tour-renderer';
import { isTourTargetVisible } from '../renderer/tour-target-visibility';
import { TourNavigation } from './tour-navigation.service';
import { anchorAppears, anchorClicks, resolveTourTarget } from './tour-target-resolver';

/**
 * `completed`: an explicit exit (Finish, Skip, close, leaving the route scope), saved as such. `stopped`: not saved
 * (stop(), or a step that failed to show).
 */
export type TourRunEnd = 'completed' | 'stopped';

const DEFAULT_SIDE: TourSide = 'bottom';
const DEFAULT_FLOATING: TourFloatingPosition = 'center';

/**
 * One run of a tour, from its first step until it ends: shows the steps on a renderer and moves between them on the
 * user's intents, clicks on targets, anchors appearing and navigations. Ends once, and then lets go of the renderer
 * and of everything it watched. Created in an injection context.
 *
 * Every way into the run (its start, the user's intents, what a step watches) is guarded: when a step fails to set up
 * or show (a definition's content function, the renderer, the DOM), or something it watches errors, the error is
 * logged and the run ends as stopped, rather than staying half-shown and blocking every other tour.
 */
export class TourRun {
    private readonly document = inject(DOCUMENT);
    private readonly dialog = inject(Dialog);
    private readonly navigation = inject(TourNavigation);
    private readonly intentSubscription: Subscription;
    /** Everything the current step watches; closed when another step starts or the run ends. */
    private stepSubscriptions = new Subscription();
    private stepIndex = 0;
    /**
     * False while the current step waits for its target or for a dialog to close. The popover on screen meanwhile
     * belongs to the step the tour has left and is shown pending, so its Next and Back mean nothing; Skip, close and
     * Escape still act on it.
     */
    private isStepShown = false;
    /** The buttons of the popover on screen, which may be the left step's; null before the first step shows. */
    private buttonsOnScreen: TourStepButtons | null = null;
    private isEnded = false;

    constructor(
        private readonly tour: TourDefinition,
        private readonly renderer: TourRenderer,
        private readonly onEnd: (end: TourRunEnd) => void
    ) {
        this.intentSubscription = renderer.intents.subscribe(this.guardedObserver((intent) => this.onIntent(intent)));
    }

    start(): void {
        this.enterStep(0);
    }

    /** Ends the run without saving it as completed. */
    stop(): void {
        this.end('stopped');
    }

    private get currentStep(): TourStep {
        return this.tour.steps[this.stepIndex];
    }

    /**
     * Makes `index` the current step. Its route scope applies at once. It shows once its target has turned up (or
     * the wait for it is over) and no CDK dialog is open: the tour would otherwise cover the dialog and trap the user.
     * Meanwhile the step on screen is pending.
     */
    private enterStep(index: number): void {
        this.stepSubscriptions.unsubscribe();
        // Kept locally too: the step may move on while it is being set up, which closes these and opens new ones.
        const subscriptions = new Subscription();
        this.stepSubscriptions = subscriptions;
        const isLeavingShownStep = this.isStepShown;
        this.isStepShown = false;
        this.stepIndex = index;
        const step = this.tour.steps[index];

        this.guarded(() => {
            if (isLeavingShownStep) {
                this.renderer.setPending(true);
            }
            if (step.routeScope) {
                subscriptions.add(
                    this.navigation.leaves(step.routeScope).subscribe(this.guardedObserver(() => this.end('completed')))
                );
            }
            subscriptions.add(
                resolveTourTarget(this.document, step.target)
                    .pipe(switchMap((target) => this.noOpenDialog().pipe(map(() => target))))
                    .subscribe(this.guardedObserver((target) => this.showStep(step, target, subscriptions)))
            );
        });
    }

    private showStep(step: TourStep, target: Element | null, subscriptions: Subscription): void {
        const showsTarget = target !== null && isTourTargetVisible(target);
        const content = !showsTarget && step.fallbackContent ? step.fallbackContent : contentOf(step, target);
        const buttons = this.buttonsOf(step);
        this.renderer.show({
            content,
            target,
            side: step.target?.side ?? DEFAULT_SIDE,
            floating: step.floating ?? DEFAULT_FLOATING,
            buttons,
            progress: this.progressOf(step),
        });
        this.isStepShown = true;
        this.buttonsOnScreen = buttons;
        this.watchAdvance(step, subscriptions);
    }

    private watchAdvance(step: TourStep, subscriptions: Subscription): void {
        const advance = step.advance;
        const anchor = step.target?.anchor;
        if (advance?.kind === 'target-click' && anchor) {
            subscriptions.add(
                anchorClicks(this.document, anchor, advance.timing).subscribe(this.guardedObserver(() => this.moveOn()))
            );
        } else if (advance?.kind === 'anchor-appears') {
            subscriptions.add(
                anchorAppears(this.document, advance.anchor).subscribe(this.guardedObserver(() => this.moveOn()))
            );
        } else if (advance?.kind === 'navigation' && advance.onTargetClick && anchor) {
            // After the target's own handlers: its router link has started the navigation the tour then follows.
            subscriptions.add(
                anchorClicks(this.document, anchor, 'after-target').subscribe(
                    this.guardedObserver(() => this.navigate(advance))
                )
            );
        }
    }

    private onIntent(intent: TourIntent): void {
        switch (intent) {
            case 'next':
                if (!this.isStepShown) {
                    return;
                }
                if (this.currentStep.advance?.kind === 'navigation') {
                    this.navigate(this.currentStep.advance);
                } else {
                    this.moveOn();
                }
                return;
            case 'back':
                if (this.isStepShown) {
                    this.goBack();
                }
                return;
            case 'skip':
            case 'close':
                this.end('completed');
                return;
            case 'escape':
                // Only where the close button is on screen: Escape stands in for it, never adds an exit of its own.
                if (this.tour.closeOnEscape && this.buttonsOnScreen?.close) {
                    this.end('completed');
                }
                return;
        }
    }

    /** To the next step; past the last one, the tour is finished. */
    private moveOn(): void {
        if (this.stepIndex === this.tour.steps.length - 1) {
            this.end('completed');
        } else {
            this.enterStep(this.stepIndex + 1);
        }
    }

    private goBack(): void {
        const toStep = this.currentStep.back?.toStep;
        const index = toStep ? this.tour.steps.findIndex((step) => step.id === toStep) : this.stepIndex - 1;
        if (index >= 0) {
            this.enterStep(index);
        }
    }

    /**
     * Pressing Next again while a navigation is on its way follows that navigation (see TourNavigation.arriveAt), so the
     * page is not asked twice; the first arrival moves on and leaving the step drops the other waits.
     */
    private navigate(advance: TourNavigationAdvance): void {
        const subscriptions = this.stepSubscriptions;
        this.guarded(() =>
            subscriptions.add(
                this.navigation
                    .arriveAt(advance.url, advance.followNavigationsInto)
                    .subscribe(this.guardedObserver(() => this.moveOn()))
            )
        );
    }

    /** Lets go of everything, and reports the end even when the renderer fails to clean up. */
    private end(end: TourRunEnd): void {
        if (this.isEnded) {
            return;
        }
        this.isEnded = true;
        this.stepSubscriptions.unsubscribe();
        this.intentSubscription.unsubscribe();
        try {
            this.renderer.dispose();
        } finally {
            this.onEnd(end);
        }
    }

    /** Runs `action`; when it throws, the run fails. */
    private guarded(action: () => void): void {
        try {
            action();
        } catch (error: unknown) {
            this.fail(error);
        }
    }

    /**
     * For everything the run subscribes to: `next` runs guarded, and an error ends the run like a throw would, instead of
     * going unhandled while the run stays open.
     */
    private guardedObserver<Value>(next: (value: Value) => void): Partial<Observer<Value>> {
        return {
            next: (value) => this.guarded(() => next(value)),
            error: (error: unknown) => this.fail(error),
        };
    }

    /** Logs `error` and ends the run as stopped, not saved. */
    private fail(error: unknown): void {
        console.error(
            `[GuidedTour] Tour "${this.tour.key}" failed on step "${this.currentStep.id}" and was stopped:`,
            error
        );
        this.end('stopped');
    }

    /** Emits once no CDK dialog is open: at once when none is. */
    private noOpenDialog(): Observable<void> {
        return this.dialog.afterAllClosed.pipe(take(1));
    }

    private buttonsOf(step: TourStep): TourStepButtons {
        const index = this.tour.steps.indexOf(step);
        const isLast = index === this.tour.steps.length - 1;
        const buttons = step.buttons ?? {};
        return {
            next: buttons.next ?? (isLast ? 'Finish' : 'Next'),
            back: index === 0 ? false : (buttons.back ?? 'Back'),
            skip: buttons.skip ?? false,
            close: buttons.close ?? true,
        };
    }

    private progressOf(step: TourStep): TourProgress | null {
        if (!step.showProgress) {
            return null;
        }
        const counted = this.tour.steps.filter((candidate) => candidate.showProgress);
        return { current: counted.indexOf(step) + 1, total: counted.length };
    }
}

/** The step's content; a content function reads only the target's attributes, never the element itself. */
function contentOf(step: TourStep, target: Element | null): TourContent {
    if (typeof step.content !== 'function') {
        return step.content;
    }
    const context: TourContentContext = { targetAttribute: (name) => target?.getAttribute(name) ?? null };
    return step.content(context);
}
