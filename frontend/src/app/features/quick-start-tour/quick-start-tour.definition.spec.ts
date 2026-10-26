import { signal, WritableSignal } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { Router, Routes } from '@angular/router';
import { Observable, of, Subject, take, tap } from 'rxjs';

import { SETTINGS_QUICKSTART_URL, SETTINGS_URL, settingsIndexGuard } from '../../core/guards/settings.guard';
import { tourAnchorSelector } from '../../core/guided-tour';
import { validateTourDefinitions } from '../../core/guided-tour/registry/validate-tour-definitions';
import { TourIntent, TourStepView } from '../../core/guided-tour/renderer/tour-renderer';
import { GuidedTourTestbed, setUpGuidedTourTestbed } from '../../core/guided-tour/testing/guided-tour-testing';
import { PermissionsService } from '../../services/auth/permissions.service';
import { createQuickStartTour, QUICK_START_TOUR_KEY } from './quick-start-tour.definition';
import { QUICK_START_RESULT_STATUS_ATTRIBUTE, QUICK_START_TOUR_ANCHORS } from './quick-start-tour-anchors';

/** A page with unsaved changes: leaving it asks the user (canDeactivate) until they choose to leave. */
const EDITOR_URL = '/editor';

describe('Quick Start tour definition', () => {
    let testbed: GuidedTourTestbed;
    let router: Router;
    let canOpenSettings: WritableSignal<boolean>;
    let canApplyQuickstart: WritableSignal<boolean>;
    let editorHasUnsavedChanges: boolean;
    /** The user's answer in the unsaved-changes dialog: true leaves, false stays. Pending until a test answers. */
    let leaveEditorAnswer: Subject<boolean>;
    let askToLeaveEditor: ReturnType<typeof vi.fn<() => Observable<boolean>>>;

    /** Like the real pages: once the user chose to leave, the changes are discarded and the page lets go. */
    function canLeaveEditor(): Observable<boolean> {
        if (!editorHasUnsavedChanges) {
            return of(true);
        }
        return askToLeaveEditor().pipe(tap((isLeaving) => (editorHasUnsavedChanges = !isLeaving)));
    }

    function createRoutes(): Routes {
        return [
            {
                path: 'settings',
                children: [
                    // The real index redirect, through a guard, as in the app.
                    { path: '', pathMatch: 'full', canActivate: [settingsIndexGuard], children: [] },
                    { path: 'quickstart', children: [] },
                    { path: 'secrets', children: [] },
                ],
            },
            { path: 'editor', canDeactivate: [() => canLeaveEditor()], children: [] },
            { path: '**', children: [] },
        ];
    }

    beforeEach(() => {
        canOpenSettings = signal(true);
        canApplyQuickstart = signal(true);
        editorHasUnsavedChanges = true;
        leaveEditorAnswer = new Subject<boolean>();
        askToLeaveEditor = vi.fn(() => leaveEditorAnswer.pipe(take(1)));
        testbed = setUpGuidedTourTestbed({
            tours: [createQuickStartTour],
            routes: createRoutes(),
            providers: [
                {
                    provide: PermissionsService,
                    useValue: {
                        can: () => true,
                        canOpenConfigureModelsDialog: () => canOpenSettings(),
                        canApplyQuickstart: () => canApplyQuickstart(),
                    },
                },
            ],
        });
        router = TestBed.inject(Router);
    });

    afterEach(() => testbed.cleanUp());

    function view(): TourStepView {
        const shown = testbed.renderer().view;
        if (!shown) {
            throw new Error('No step is shown.');
        }
        return shown;
    }

    /** The step's text as read, formatting dropped. */
    function bodyText(): string {
        return view()
            .content.body.map((paragraph) =>
                typeof paragraph === 'string' ? paragraph : paragraph.map((run) => run.text).join('')
            )
            .join(' ');
    }

    function press(...intents: TourIntent[]): void {
        intents.forEach((intent) => testbed.renderer().press(intent));
    }

    function clickAnchor(anchor: string): void {
        document.querySelector<HTMLElement>(tourAnchorSelector(anchor))?.click();
    }

    async function routerSettled(): Promise<void> {
        await vi.waitFor(() => expect(router.currentNavigation()).toBeNull());
    }

    /** The Quickstart tab as rendered (before Activate): the tab, the provider select and its open list, the key. */
    function appendQuickstartTab(): void {
        testbed.appendAnchor(QUICK_START_TOUR_ANCHORS.quickstartTab);
        testbed.appendAnchor(QUICK_START_TOUR_ANCHORS.quickstartProvider);
        testbed.appendAnchor(QUICK_START_TOUR_ANCHORS.quickstartProviderList);
        testbed.appendAnchor(QUICK_START_TOUR_ANCHORS.quickstartApiKey);
        testbed.appendAnchor(QUICK_START_TOUR_ANCHORS.quickstartActivate);
    }

    function appendResultCard(status: string): HTMLElement {
        const card = testbed.appendAnchor(QUICK_START_TOUR_ANCHORS.quickstartResult);
        card.setAttribute(QUICK_START_RESULT_STATUS_ATTRIBUTE, status);
        return card;
    }

    /** Lets a MutationObserver see a DOM change. */
    async function domObserved(): Promise<void> {
        await Promise.resolve();
        await Promise.resolve();
    }

    /** Starts on the Quickstart tab and walks to the Activate step the way a user does. */
    async function walkToActivate(): Promise<void> {
        appendQuickstartTab();
        await router.navigateByUrl(SETTINGS_QUICKSTART_URL);
        await testbed.service.start(QUICK_START_TOUR_KEY);
        press('next', 'next', 'next');
        clickAnchor(QUICK_START_TOUR_ANCHORS.quickstartProvider);
        clickAnchor(QUICK_START_TOUR_ANCHORS.quickstartProviderList);
        press('next');
        expect(view().content.title).toBe('Activate');
    }

    it('is a valid tour definition', () => {
        const definition = TestBed.runInInjectionContext(createQuickStartTour);

        expect(validateTourDefinitions([definition]).problems).toEqual([]);
    });

    it('starts by itself for a signed-in user who has not completed it', async () => {
        testbed.connectAppShell();

        testbed.progressStore.signIn(1);
        await testbed.settle();

        expect(testbed.service.activeTour()?.key).toBe('quick-start');
    });

    it.each([
        ['with both permissions', true, true, true],
        ['without access to Settings', false, true, false],
        ['without permission to apply Quickstart', true, false, false],
    ])('is available only with both permissions: %s', (_case, settings, quickstart, isAvailable) => {
        canOpenSettings.set(settings);
        canApplyQuickstart.set(quickstart);

        expect(testbed.service.replayableTours().some((tour) => tour.key === 'quick-start')).toBe(isAvailable);
    });

    it('welcomes with the image, Get started and Skip; Skip saves it as completed', async () => {
        await testbed.service.start(QUICK_START_TOUR_KEY);

        expect(view().content.title).toBe('Welcome to Quick Start!');
        expect(view().content.media?.src).toBe('assets/quick-start-guide/quick-start-guide-welcome.webp');
        expect(view().buttons).toEqual({ next: 'Get started', back: false, skip: 'Skip', close: true });
        expect(view().progress).toBeNull();
        press('skip');
        expect(testbed.progressStore.savedTourKeys).toEqual(['quick-start']);
    });

    it('ignores Escape, as before', async () => {
        await testbed.service.start(QUICK_START_TOUR_KEY);

        press('escape');

        expect(testbed.renderer().isDisposed).toBe(false);
    });

    describe('Open Settings', () => {
        it('points at the Settings icon as step 1 of 6', async () => {
            const icon = testbed.appendAnchor(QUICK_START_TOUR_ANCHORS.sidenavSettings);
            await testbed.service.start(QUICK_START_TOUR_KEY);

            press('next');

            expect(view().target).toBe(icon);
            expect(view().side).toBe('right');
            expect(view().progress).toEqual({ current: 1, total: 6 });
            expect(bodyText()).toContain('Click the Settings icon');
        });

        it('on a phone, where the icon is hidden, floats with copy that works without it; Next opens Settings', async () => {
            testbed.appendAnchor(QUICK_START_TOUR_ANCHORS.sidenavSettings, { hidden: true });
            testbed.appendAnchor(QUICK_START_TOUR_ANCHORS.quickstartTab);
            await router.navigateByUrl('/agents');
            await testbed.service.start(QUICK_START_TOUR_KEY);
            press('next');

            expect(view().content.title).toBe('Open Settings');
            expect(bodyText()).toContain('Press Next to open Settings');
            expect(view().floating).toBe('center');

            press('next');
            await routerSettled();
            expect(router.url).toBe(SETTINGS_QUICKSTART_URL);
            expect(view().content.title).toBe('Quickstart');
        });

        it('follows the Settings link the user clicked, so the page being left asks only once', async () => {
            const icon = testbed.appendAnchor(QUICK_START_TOUR_ANCHORS.sidenavSettings);
            testbed.appendAnchor(QUICK_START_TOUR_ANCHORS.quickstartTab);
            await router.navigateByUrl(EDITOR_URL);
            await testbed.service.start(QUICK_START_TOUR_KEY);
            press('next');

            // A real click: the icon's router link navigates first, up to the unsaved-changes question.
            void router.navigateByUrl(SETTINGS_URL);
            await vi.waitFor(() => expect(askToLeaveEditor).toHaveBeenCalledTimes(1));
            icon.click();
            leaveEditorAnswer.next(true);
            await routerSettled();

            expect(router.url).toBe(SETTINGS_QUICKSTART_URL);
            expect(askToLeaveEditor).toHaveBeenCalledTimes(1);
            expect(view().content.title).toBe('Quickstart');
        });
    });

    it('moves on from the provider select and its list on a click, and Back from the API key skips the closed list', async () => {
        appendQuickstartTab();
        await router.navigateByUrl(SETTINGS_QUICKSTART_URL);
        await testbed.service.start(QUICK_START_TOUR_KEY);
        press('next', 'next', 'next');
        expect(view().content.title).toBe('Pick a provider');
        expect(view().buttons).toMatchObject({ next: false, back: 'Back' });

        clickAnchor(QUICK_START_TOUR_ANCHORS.quickstartProvider);
        expect(view().content.title).toBe('Select a provider');
        expect(view().buttons).toEqual({ next: false, back: false, skip: false, close: true });

        clickAnchor(QUICK_START_TOUR_ANCHORS.quickstartProviderList);
        expect(view().content.title).toBe('Add your API key');

        press('back');
        expect(view().content.title).toBe('Pick a provider');
    });

    it('stays on Activate, without Next, until the result card renders', async () => {
        await walkToActivate();
        expect(view().buttons.next).toBe(false);
        expect(view().progress).toEqual({ current: 6, total: 6 });

        appendResultCard('activated');
        await domObserved();

        expect(view().buttons).toEqual({ next: 'Finish', back: false, skip: false, close: true });
        expect(view().progress).toBeNull();
    });

    it.each<[status: string, title: string, strongText: string | null]>([
        ['activated', 'You’re all set', null],
        ['updated', 'One more step', 'Update default models'],
    ])('ends with the copy for the %s result card', async (status, title, strongText) => {
        await walkToActivate();

        appendResultCard(status);
        await domObserved();

        const strongRuns = view()
            .content.body.flatMap((paragraph) => (typeof paragraph === 'string' ? [] : paragraph))
            .filter((run) => run.strong)
            .map((run) => run.text);
        expect(view().content.title).toBe(title);
        expect(strongRuns).toEqual(strongText ? [strongText] : []);
    });

    it('treats an unexpected result status as activated', async () => {
        await walkToActivate();

        appendResultCard('unknown');
        await domObserved();

        expect(view().content.title).toBe('You’re all set');
    });

    it('finishes before a button in the result card handles its click (its confirm dialog must be usable)', async () => {
        await walkToActivate();
        const card = appendResultCard('updated');
        const updateButton = card.appendChild(document.createElement('button'));
        const tourEndedBeforeHandler = vi.fn();
        updateButton.addEventListener('click', () => tourEndedBeforeHandler(testbed.renderer().isDisposed));
        await domObserved();

        updateButton.click();

        expect(tourEndedBeforeHandler).toHaveBeenCalledWith(true);
        expect(testbed.progressStore.savedTourKeys).toEqual(['quick-start']);
    });

    it('ends, and saves, when the user leaves the Quickstart tab', async () => {
        appendQuickstartTab();
        await router.navigateByUrl(SETTINGS_QUICKSTART_URL);
        await testbed.service.start(QUICK_START_TOUR_KEY);
        press('next', 'next');
        expect(view().content.title).toBe('Quickstart');

        await router.navigateByUrl('/settings/secrets');

        expect(testbed.renderer().isDisposed).toBe(true);
        expect(testbed.progressStore.savedTourKeys).toEqual(['quick-start']);
    });
});
