import { inject } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { Router, Routes } from '@angular/router';
import { Observable, of, Subject, take, tap } from 'rxjs';

import { TourDefinition } from '../model/tour-definition';
import { GuidedTourTestbed, setUpGuidedTourTestbed } from '../testing/guided-tour-testing';

/** The section index redirects to its first tab through a guard, which makes the redirect a second navigation. */
const SECTION_URL = '/section';
const TAB_URL = '/section/tab';
/** A page with unsaved changes: leaving it runs a canDeactivate guard, like UnsavedChangesGuard on the real pages. */
const EDITOR_URL = '/editor';
/** A page whose canActivate is still checking: a navigation to it stays in flight until a test answers. */
const SLOW_PAGE_URL = '/slow-page';
const LINK_ANCHOR = 'section-link';

function navigatingTour(): TourDefinition {
    return {
        key: 'navigating',
        label: 'Navigating',
        icon: 'help',
        autoStart: 'manual',
        isAvailable: () => true,
        steps: [
            { id: 'intro', content: { title: 'Intro', body: [] } },
            {
                id: 'open',
                content: { title: 'Open the section', body: [] },
                target: { anchor: LINK_ANCHOR, side: 'right' },
                advance: { kind: 'navigation', url: TAB_URL, followNavigationsInto: SECTION_URL, onTargetClick: true },
            },
            { id: 'tab', content: { title: 'On the tab', body: [] }, routeScope: TAB_URL },
            { id: 'more', content: { title: 'More', body: [] }, routeScope: TAB_URL },
        ],
    };
}

describe('TourNavigation', () => {
    let testbed: GuidedTourTestbed;
    let router: Router;
    let link: HTMLElement;
    let editorHasUnsavedChanges: boolean;
    /** The user's answer in the unsaved-changes dialog: true leaves, false stays. Pending until a test answers. */
    let leaveEditorAnswer: Subject<boolean>;
    /** The unsaved-changes dialog. */
    let askToLeaveEditor: ReturnType<typeof vi.fn<() => Observable<boolean>>>;
    /** The slow page's canActivate answer; pending until a test answers. */
    let slowPageAccess: Subject<boolean>;
    let canEnterSlowPage: ReturnType<typeof vi.fn<() => Observable<boolean>>>;

    /**
     * Like the real pages' canDeactivate: asks while there are unsaved changes; once the user chose to leave, the
     * changes are discarded and the page lets go without asking. That matters because the section index redirect is a
     * second navigation, which asks the page again.
     */
    function canLeaveEditor(): Observable<boolean> {
        if (!editorHasUnsavedChanges) {
            return of(true);
        }
        return askToLeaveEditor().pipe(tap((isLeaving) => (editorHasUnsavedChanges = !isLeaving)));
    }

    function createRoutes(): Routes {
        return [
            {
                path: 'section',
                children: [
                    {
                        path: '',
                        pathMatch: 'full',
                        canActivate: [() => inject(Router).parseUrl(TAB_URL)],
                        children: [],
                    },
                    { path: 'tab', children: [] },
                    { path: 'other', children: [] },
                ],
            },
            { path: 'editor', canDeactivate: [() => canLeaveEditor()], children: [] },
            { path: 'slow-page', canActivate: [() => canEnterSlowPage()], children: [] },
            { path: '**', children: [] },
        ];
    }

    beforeEach(() => {
        editorHasUnsavedChanges = true;
        leaveEditorAnswer = new Subject<boolean>();
        askToLeaveEditor = vi.fn(() => leaveEditorAnswer.pipe(take(1)));
        slowPageAccess = new Subject<boolean>();
        canEnterSlowPage = vi.fn(() => slowPageAccess.pipe(take(1)));
        testbed = setUpGuidedTourTestbed({ tours: [navigatingTour], routes: createRoutes() });
        router = TestBed.inject(Router);
        link = testbed.appendAnchor(LINK_ANCHOR, { tagName: 'a' });
    });

    afterEach(() => testbed.cleanUp());

    function shownTitle(): string | undefined {
        return testbed.renderer().view?.content.title;
    }

    async function routerSettled(): Promise<void> {
        await vi.waitFor(() => expect(router.currentNavigation()).toBeNull());
    }

    /** Waits until the router has settled on the tab (the index redirect is a second navigation). */
    async function expectOnTab(): Promise<void> {
        await routerSettled();
        expect(router.url).toBe(TAB_URL);
    }

    /** Starts the tour from `url` and moves to its navigation step. */
    async function startOnNavigationStep(url = '/agents'): Promise<void> {
        await router.navigateByUrl(url);
        await testbed.service.start('navigating');
        testbed.renderer().press('next');
    }

    async function arriveOnTab(): Promise<void> {
        await startOnNavigationStep();
        testbed.renderer().press('next');
        await expectOnTab();
        expect(shownTitle()).toBe('On the tab');
    }

    /**
     * Leaves the page with unsaved changes for the section, until the user is asked about them. `link` is a click on
     * the target in the order a browser runs it: the target's router link starts its navigation, the router gets as
     * far as it can (to the unsaved-changes dialog), and only then does the tour's document listener see the click.
     * `Next` is the popover's button.
     */
    async function leaveEditorForSection(trigger: 'link' | 'Next'): Promise<void> {
        const timesAsked = askToLeaveEditor.mock.calls.length;
        if (trigger === 'link') {
            void router.navigateByUrl(SECTION_URL);
            await vi.waitFor(() => expect(askToLeaveEditor).toHaveBeenCalledTimes(timesAsked + 1));
            link.click();
        } else {
            testbed.renderer().press('next');
            await vi.waitFor(() => expect(askToLeaveEditor).toHaveBeenCalledTimes(timesAsked + 1));
        }
    }

    describe('navigation step', () => {
        it('on Next, opens the URL and moves on only once it is shown', async () => {
            await startOnNavigationStep();

            testbed.renderer().press('next');
            expect(shownTitle()).toBe('Open the section');

            await expectOnTab();
            expect(shownTitle()).toBe('On the tab');
            // The tour's own navigation is not the user leaving the scope.
            expect(testbed.renderer().isDisposed).toBe(false);
            expect(testbed.progressStore.savedTourKeys).toEqual([]);
        });

        it('moves on at once, without navigating, when the URL is already shown', async () => {
            await startOnNavigationStep(TAB_URL);
            const navigateByUrl = vi.spyOn(router, 'navigateByUrl');

            testbed.renderer().press('next');

            expect(shownTitle()).toBe('On the tab');
            expect(navigateByUrl).not.toHaveBeenCalled();
        });

        it('moves on without navigating again when the target link already got there', async () => {
            await startOnNavigationStep();
            const navigateByUrl = vi.spyOn(router, 'navigateByUrl');

            // With nothing to ask, a real click's link navigation (and the redirect) is done before the tour sees it.
            void router.navigateByUrl(SECTION_URL);
            await routerSettled();
            link.click();

            expect(navigateByUrl).toHaveBeenCalledExactlyOnceWith(SECTION_URL);
            expect(shownTitle()).toBe('On the tab');
        });

        it.each(['link', 'Next'] as const)(
            'via the %s, asks the page being left once, and moves on when the user leaves it',
            async (trigger) => {
                await startOnNavigationStep(EDITOR_URL);

                await leaveEditorForSection(trigger);
                expect(shownTitle()).toBe('Open the section');
                leaveEditorAnswer.next(true);
                await expectOnTab();

                expect(askToLeaveEditor).toHaveBeenCalledTimes(1);
                expect(shownTitle()).toBe('On the tab');
                expect(testbed.progressStore.savedTourKeys).toEqual([]);
            }
        );

        it.each(['link', 'Next'] as const)(
            'via the %s, stays on the step, saving nothing, when the user stays; and can try again',
            async (trigger) => {
                await startOnNavigationStep(EDITOR_URL);

                await leaveEditorForSection(trigger);
                leaveEditorAnswer.next(false);
                await routerSettled();

                expect(router.url).toBe(EDITOR_URL);
                expect(askToLeaveEditor).toHaveBeenCalledTimes(1);
                expect(shownTitle()).toBe('Open the section');
                expect(testbed.progressStore.savedTourKeys).toEqual([]);

                await leaveEditorForSection(trigger);
                leaveEditorAnswer.next(true);
                await expectOnTab();
                expect(askToLeaveEditor).toHaveBeenCalledTimes(2);
                expect(shownTitle()).toBe('On the tab');
            }
        );

        it('ignores a second Next while the navigation is on its way', async () => {
            await startOnNavigationStep(EDITOR_URL);
            await leaveEditorForSection('link');

            testbed.renderer().press('next');
            leaveEditorAnswer.next(true);
            await expectOnTab();

            expect(askToLeaveEditor).toHaveBeenCalledTimes(1);
            // One step on, not two.
            expect(shownTitle()).toBe('On the tab');
        });

        it('supersedes an unrelated navigation in flight with its own, and moves on once there', async () => {
            await startOnNavigationStep();
            void router.navigateByUrl(SLOW_PAGE_URL);
            await vi.waitFor(() => expect(canEnterSlowPage).toHaveBeenCalled());
            const navigateByUrl = vi.spyOn(router, 'navigateByUrl');

            testbed.renderer().press('next');
            await expectOnTab();

            expect(navigateByUrl).toHaveBeenCalledExactlyOnceWith(TAB_URL);
            expect(shownTitle()).toBe('On the tab');
            // The superseded navigation's guard answering late changes nothing.
            slowPageAccess.next(true);
            await routerSettled();
            expect(router.url).toBe(TAB_URL);
        });

        // Stands in for a slow network: the navigation is still on its way when the user goes Back.
        it('Back drops a navigation on its way: arriving later does not move on', async () => {
            await startOnNavigationStep(EDITOR_URL);
            await leaveEditorForSection('Next');

            testbed.renderer().press('back');
            leaveEditorAnswer.next(true);
            await expectOnTab();
            await router.navigateByUrl('/agents');

            expect(shownTitle()).toBe('Intro');
            expect(testbed.progressStore.savedTourKeys).toEqual([]);
        });

        it('stop() while a navigation is on its way: arriving afterwards changes nothing', async () => {
            await startOnNavigationStep(EDITOR_URL);
            await leaveEditorForSection('Next');
            const shownSteps = testbed.renderer().views.length;

            testbed.service.stop();
            leaveEditorAnswer.next(true);
            await expectOnTab();
            await router.navigateByUrl('/agents');

            expect(testbed.renderer().views).toHaveLength(shownSteps);
            expect(testbed.progressStore.savedTourKeys).toEqual([]);
        });
    });

    describe('route scope', () => {
        it.each([
            ['another page', '/agents'],
            ['another tab of the section', '/section/other'],
        ])('ends the tour, and saves it once, when the user leaves for %s', async (_target, url) => {
            await arriveOnTab();

            await router.navigateByUrl(url);
            await router.navigateByUrl(TAB_URL);
            await router.navigateByUrl(url);

            expect(testbed.renderer().isDisposed).toBe(true);
            expect(testbed.progressStore.savedTourKeys).toEqual(['navigating']);
        });

        it('applies on every step that has it', async () => {
            await arriveOnTab();
            testbed.renderer().press('next');
            expect(shownTitle()).toBe('More');

            await router.navigateByUrl('/agents');

            expect(testbed.progressStore.savedTourKeys).toEqual(['navigating']);
        });

        it('does not take query parameters or a fragment as leaving', async () => {
            await arriveOnTab();

            await router.navigateByUrl(`${TAB_URL}?provider=openai#api-key`);

            expect(testbed.renderer().isDisposed).toBe(false);
        });

        it('stops applying on Back to a step without it; the page stays where it is', async () => {
            await arriveOnTab();

            testbed.renderer().press('back');
            expect(router.url).toBe(TAB_URL);
            await router.navigateByUrl('/agents');

            expect(shownTitle()).toBe('Open the section');
            expect(testbed.progressStore.savedTourKeys).toEqual([]);
        });

        it.each<[exit: string, savedBefore: string[], endTour: () => void]>([
            ['stopped', [], () => testbed.service.stop()],
            ['closed', ['navigating'], () => testbed.renderer().press('close')],
        ])(
            'stops applying once the tour is %s, so the next run applies it afresh',
            async (_exit, savedBefore, endTour) => {
                await arriveOnTab();
                endTour();
                await router.navigateByUrl('/agents');
                expect(testbed.progressStore.savedTourKeys).toEqual(savedBefore);

                await arriveOnTab();
                await router.navigateByUrl('/agents');

                expect(testbed.renderer().isDisposed).toBe(true);
                expect(testbed.progressStore.savedTourKeys).toEqual([...savedBefore, 'navigating']);
            }
        );
    });
});
