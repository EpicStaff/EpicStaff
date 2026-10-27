import { Dialog } from '@angular/cdk/dialog';
import {
    Component,
    createEnvironmentInjector,
    DestroyRef,
    EnvironmentInjector,
    signal,
    WritableSignal,
} from '@angular/core';
import { TestBed } from '@angular/core/testing';

import { TourDefinition, TourStep } from '../model/tour-definition';
import { TourIntent } from '../renderer/tour-renderer';
import { GuidedTourTestbed, setUpGuidedTourTestbed } from '../testing/guided-tour-testing';

@Component({ template: 'You have unsaved changes.' })
class UnsavedChangesDialogComponent {}

const TWO_STEPS: TourStep[] = [
    { id: 'welcome', content: { title: 'Welcome', body: [] } },
    { id: 'done', content: { title: 'Done', body: [] } },
];

/** Runs `action` as a production build would (no dev mode). */
async function inProduction(action: () => void | Promise<void>): Promise<void> {
    vi.stubGlobal('ngDevMode', false);
    try {
        await action();
    } finally {
        vi.unstubAllGlobals();
    }
}

describe('GuidedTourService', () => {
    let testbed: GuidedTourTestbed;
    let isIntroAvailable: WritableSignal<boolean>;
    let isGuideAvailable: WritableSignal<boolean>;
    /** Keys of the tours whose `isAvailable` throws, like a definition with a bug in it. */
    let toursWithFailingAvailability: Set<string>;

    function availability(key: string, isAvailable: () => boolean): () => boolean {
        return () => {
            if (toursWithFailingAvailability.has(key)) {
                throw new Error(`The availability check of "${key}" failed`);
            }
            return isAvailable();
        };
    }

    /** Auto-starts until completed. */
    function introTour(): TourDefinition {
        return {
            key: 'intro',
            label: 'Intro',
            icon: 'help',
            autoStart: 'until-completed',
            isAvailable: availability('intro', () => isIntroAvailable()),
            steps: TWO_STEPS,
        };
    }

    /** Started by the user only. */
    function guideTour(): TourDefinition {
        return {
            ...introTour(),
            key: 'guide',
            label: 'Guide',
            autoStart: 'manual',
            isAvailable: availability('guide', () => isGuideAvailable()),
        };
    }

    /** Auto-starts until completed, after intro. */
    function laterTour(): TourDefinition {
        return { ...introTour(), key: 'later', label: 'Later', isAvailable: () => true };
    }

    /** Started by the user only; Escape ends it where the close button shows, which the second step hides. */
    function escapableTour(): TourDefinition {
        return {
            ...guideTour(),
            key: 'escapable',
            label: 'Escapable',
            isAvailable: () => true,
            closeOnEscape: true,
            steps: [TWO_STEPS[0], { ...TWO_STEPS[1], buttons: { close: false } }],
        };
    }

    beforeEach(() => {
        isIntroAvailable = signal(true);
        isGuideAvailable = signal(true);
        toursWithFailingAvailability = new Set();
        testbed = setUpGuidedTourTestbed({ tours: [introTour, guideTour, laterTour, escapableTour] });
    });

    afterEach(() => testbed.cleanUp());

    function shownTitle(): string | undefined {
        return testbed.renderer().view?.content.title;
    }

    describe('start', () => {
        it('shows the first step of the tour', async () => {
            await testbed.service.start('guide');

            expect(shownTitle()).toBe('Welcome');
            expect(testbed.service.activeTour()?.key).toBe('guide');
        });

        it('does nothing for a tour the user cannot take', async () => {
            isGuideAvailable.set(false);

            await testbed.service.start('guide');

            expect(testbed.renderers).toHaveLength(0);
            expect(testbed.service.activeTour()).toBeNull();
        });

        it('does nothing, and logs, for a key no tour is registered as', async () => {
            const consoleError = vi.spyOn(console, 'error').mockImplementation(() => undefined);

            await testbed.service.start('missing');

            expect(testbed.renderers).toHaveLength(0);
            expect(consoleError).toHaveBeenCalled();
            consoleError.mockRestore();
        });

        it('runs one tour at a time: a start while another is starting or running does nothing', async () => {
            await Promise.all([testbed.service.start('guide'), testbed.service.start('intro')]);
            await testbed.service.start('intro');

            expect(testbed.renderers).toHaveLength(1);
            expect(testbed.service.activeTour()?.key).toBe('guide');
        });

        it('can start a tour again once it has ended', async () => {
            await testbed.service.start('guide');
            testbed.renderer().press('close');

            await testbed.service.start('guide');

            expect(testbed.renderers).toHaveLength(2);
            expect(shownTitle()).toBe('Welcome');
        });

        it('logs and recovers when the renderer cannot be loaded', async () => {
            const consoleError = vi.spyOn(console, 'error').mockImplementation(() => undefined);
            testbed.failNextRendererLoad();

            await testbed.service.start('guide');
            expect(consoleError).toHaveBeenCalled();
            expect(testbed.service.activeTour()).toBeNull();
            consoleError.mockRestore();

            await testbed.service.start('guide');
            expect(shownTitle()).toBe('Welcome');
        });

        it('shows nothing, and saves nothing, when stopped while the renderer loads', async () => {
            const releaseRendererLoads = testbed.holdRendererLoads();

            const starting = testbed.service.start('guide');
            testbed.service.stop();
            releaseRendererLoads();
            await starting;

            const renderer = testbed.renderer();
            expect(renderer.views).toHaveLength(0);
            expect(renderer.isDisposed).toBe(true);
            expect(testbed.service.activeTour()).toBeNull();
            expect(testbed.progressStore.savedTourKeys).toEqual([]);
        });

        it('waits for an open dialog to close before it shows the first step', async () => {
            const dialogRef = TestBed.inject(Dialog).open(UnsavedChangesDialogComponent);

            await testbed.service.start('guide');
            expect(testbed.renderer().views).toHaveLength(0);
            // Starting, so no other tour may start meanwhile.
            await testbed.service.start('intro');
            expect(testbed.service.activeTour()?.key).toBe('guide');

            dialogRef.close();

            expect(shownTitle()).toBe('Welcome');
        });
    });

    describe('exits', () => {
        it.each<[exit: string, intents: TourIntent[]]>([
            ['Finish on the last step', ['next', 'next']],
            ['Skip', ['skip']],
            ['the close button', ['close']],
        ])('saves %s as completed, once, and ends the tour', async (_exit, intents) => {
            await testbed.service.start('guide');
            const renderer = testbed.renderer();

            intents.forEach((intent) => renderer.press(intent));
            renderer.press('close');

            expect(renderer.isDisposed).toBe(true);
            expect(testbed.service.activeTour()).toBeNull();
            expect(testbed.progressStore.savedTourKeys).toEqual(['guide']);
        });

        it.each<[description: string, key: string, step: number, isDisposed: boolean, savedTourKeys: string[]]>([
            ['is ignored by a tour that does not allow it', 'guide', 0, false, []],
            [
                'ends, and saves, a tour that allows it, on a step with the close button',
                'escapable',
                0,
                true,
                ['escapable'],
            ],
            ['is ignored on a step without the close button, even in a tour that allows it', 'escapable', 1, false, []],
        ])('Escape %s', async (_description, key, step, isDisposed, savedTourKeys) => {
            await testbed.service.start(key);
            for (let pressed = 0; pressed < step; pressed++) {
                testbed.renderer().press('next');
            }

            testbed.renderer().press('escape');

            expect(testbed.renderer().isDisposed).toBe(isDisposed);
            expect(testbed.progressStore.savedTourKeys).toEqual(savedTourKeys);
        });

        it('stop() ends the tour without saving it', async () => {
            await testbed.service.start('guide');

            testbed.service.stop();

            expect(testbed.renderer().isDisposed).toBe(true);
            expect(testbed.service.activeTour()).toBeNull();
            expect(testbed.progressStore.savedTourKeys).toEqual([]);
        });

        it('logs, and does not throw, when saving the completion fails', async () => {
            const consoleError = vi.spyOn(console, 'error').mockImplementation(() => undefined);
            testbed.progressStore.failSaves = true;
            await testbed.service.start('guide');

            expect(() => testbed.renderer().press('close')).not.toThrow();
            expect(consoleError).toHaveBeenCalled();
            expect(testbed.service.activeTour()).toBeNull();
            consoleError.mockRestore();
        });

        it('keeps running when the tour becomes unavailable mid-run (an org switch clears permissions for a moment)', async () => {
            await testbed.service.start('guide');

            isGuideAvailable.set(false);
            await testbed.settle();

            expect(testbed.renderer().isDisposed).toBe(false);
            expect(testbed.service.activeTour()?.key).toBe('guide');
        });
    });

    describe('auto-start', () => {
        async function signIn(userId = 1, completedTourKeys: string[] = []): Promise<void> {
            testbed.progressStore.signIn(userId, completedTourKeys);
            await testbed.settle();
        }

        it('starts an auto-start tour for a signed-in user who has not completed it', async () => {
            testbed.connectAppShell();

            await signIn();

            expect(testbed.service.activeTour()?.key).toBe('intro');
            expect(shownTitle()).toBe('Welcome');
        });

        it('does not start a tour the user has completed', async () => {
            testbed.connectAppShell();

            await signIn(1, ['intro', 'later']);

            expect(testbed.renderers).toHaveLength(0);
        });

        it('waits until a user is signed in', async () => {
            testbed.connectAppShell();
            await testbed.settle();
            expect(testbed.renderers).toHaveLength(0);

            await signIn();

            expect(testbed.service.activeTour()?.key).toBe('intro');
        });

        it('starts nothing without an app shell', async () => {
            await signIn();

            expect(testbed.renderers).toHaveLength(0);
        });

        it('decides once per user: an ended tour does not start again', async () => {
            // A failed save leaves the tour uncompleted, so only that decision keeps it from starting again.
            const consoleError = vi.spyOn(console, 'error').mockImplementation(() => undefined);
            testbed.progressStore.failSaves = true;
            testbed.connectAppShell();
            await signIn(1, ['later']);

            testbed.renderer().press('close');
            await testbed.settle();

            expect(testbed.renderers).toHaveLength(1);
            expect(testbed.service.activeTour()).toBeNull();
            consoleError.mockRestore();
        });

        it('does not start while the user cannot take the tour, and does once they can (org switch)', async () => {
            isIntroAvailable.set(false);
            testbed.connectAppShell();
            await signIn(1, ['later']);
            expect(testbed.renderers).toHaveLength(0);

            isIntroAvailable.set(true);
            await testbed.settle();

            expect(testbed.service.activeTour()?.key).toBe('intro');
        });

        it('re-arms on sign-out: the same user signing in again gets the tour again', async () => {
            testbed.connectAppShell();
            await signIn(1, ['later']);
            testbed.service.stop();

            testbed.progressStore.signOut();
            await testbed.settle();
            await signIn(1, ['later']);

            expect(testbed.renderers).toHaveLength(2);
            expect(testbed.service.activeTour()?.key).toBe('intro');
        });

        it('re-arms on sign-out also when the app shell goes away with it, as it does in the app', async () => {
            const disconnectFirstShell = testbed.connectAppShell();
            await signIn(1, ['later']);
            disconnectFirstShell();
            testbed.progressStore.signOut();
            await testbed.settle();

            testbed.connectAppShell();
            await signIn(1, ['later']);

            expect(testbed.renderers).toHaveLength(2);
            expect(testbed.service.activeTour()?.key).toBe('intro');
        });

        it('keeps its decisions for the signed-in user across app shells', async () => {
            const disconnectFirstShell = testbed.connectAppShell();
            await signIn(1, ['later']);
            disconnectFirstShell();

            testbed.connectAppShell();
            await testbed.settle();

            expect(testbed.renderers).toHaveLength(1);
            expect(testbed.service.activeTour()).toBeNull();
        });

        it('decides afresh for another user', async () => {
            testbed.connectAppShell();
            await signIn(1, ['later']);
            testbed.service.stop();

            await signIn(2, ['later']);

            expect(testbed.renderers).toHaveLength(2);
            expect(testbed.service.activeTour()?.key).toBe('intro');
        });

        it('does not start a tour the user started and ended while its completion is still being saved', async () => {
            testbed.progressStore.holdSaves();
            await signIn(1, ['later']);
            await testbed.service.start('intro');
            testbed.connectAppShell();
            await testbed.settle();

            testbed.renderer().press('close');
            await testbed.settle();

            expect(testbed.progressStore.savedTourKeys).toEqual(['intro']);
            expect(testbed.renderers).toHaveLength(1);
            expect(testbed.service.activeTour()).toBeNull();
        });

        it('does not start again a tour the user started while the profile was still loading', async () => {
            testbed.progressStore.holdSaves();
            testbed.connectAppShell();
            await testbed.service.start('intro');
            await testbed.settle();
            await signIn(1, ['later']);

            testbed.renderer().press('close');
            await testbed.settle();

            expect(testbed.renderers).toHaveLength(1);
            expect(testbed.service.activeTour()).toBeNull();
        });

        it('takes one app shell at a time (dev mode): a second throws until the first is gone', () => {
            const disconnectFirstShell = testbed.connectAppShell();

            expect(() => testbed.connectAppShell()).toThrow('An app shell is already connected');
            disconnectFirstShell();
            expect(() => testbed.connectAppShell()).not.toThrow();
        });

        it('lets a second app shell connect in production, and still starts each tour once', async () => {
            await inProduction(async () => {
                testbed.connectAppShell();
                expect(() => testbed.connectAppShell()).not.toThrow();
                await signIn();
            });

            expect(testbed.renderers).toHaveLength(1);
            expect(testbed.service.activeTour()?.key).toBe('intro');
        });

        it('leaves nothing running for an app shell that is already gone', async () => {
            const shell = createEnvironmentInjector([], TestBed.inject(EnvironmentInjector));
            const shellDestroyRef = shell.get(DestroyRef);
            shell.destroy();

            expect(() => testbed.service.connectAppShell(shellDestroyRef)).toThrow();
            await signIn();

            expect(testbed.renderers).toHaveLength(0);
        });

        it('considers the tours in registry order, one at a time, and the next once the active one ends', async () => {
            testbed.connectAppShell();
            await signIn();
            expect(testbed.service.activeTour()?.key).toBe('intro');

            testbed.renderer().press('close');
            await testbed.settle();

            expect(testbed.service.activeTour()?.key).toBe('later');
            expect(testbed.renderers).toHaveLength(2);
        });

        it('never starts a manual tour by itself', async () => {
            testbed.connectAppShell();

            await signIn(1, ['intro', 'later']);

            expect(testbed.renderers).toHaveLength(0);
        });

        it('waits for a tour the user started to end', async () => {
            await testbed.service.start('guide');
            testbed.connectAppShell();
            await signIn();
            expect(testbed.service.activeTour()?.key).toBe('guide');

            testbed.renderer().press('close');
            await testbed.settle();

            expect(testbed.service.activeTour()?.key).toBe('intro');
        });

        it('stops the active tour, without saving it, when the app shell goes away', async () => {
            const disconnectShell = testbed.connectAppShell();
            await signIn();

            disconnectShell();

            expect(testbed.renderer().isDisposed).toBe(true);
            expect(testbed.service.activeTour()).toBeNull();
            expect(testbed.progressStore.savedTourKeys).toEqual([]);
        });
    });

    describe('replayableTours', () => {
        it('lists the tours the user can take now, in registry order', () => {
            isGuideAvailable.set(false);
            expect(testbed.service.replayableTours().map((tour) => tour.key)).toEqual(['intro', 'later', 'escapable']);

            isGuideAvailable.set(true);
            isIntroAvailable.set(false);
            expect(testbed.service.replayableTours().map((tour) => tour.key)).toEqual(['guide', 'later', 'escapable']);
        });
    });

    describe('a tour whose availability check throws', () => {
        it('fails loudly in dev mode, like the registry checks', () => {
            toursWithFailingAvailability.add('guide');

            expect(() => testbed.service.replayableTours()).toThrow('The availability check of "guide" failed');
        });

        it('in production, counts as unavailable, is logged once, and does not hold up the other tours', async () => {
            const consoleError = vi.spyOn(console, 'error').mockImplementation(() => undefined);
            toursWithFailingAvailability.add('intro');

            await inProduction(async () => {
                expect(testbed.service.replayableTours().map((tour) => tour.key)).toEqual([
                    'guide',
                    'later',
                    'escapable',
                ]);
                await testbed.service.start('intro');
                expect(testbed.renderers).toHaveLength(0);

                testbed.connectAppShell();
                testbed.progressStore.signIn(1);
                await testbed.settle();
            });

            expect(testbed.service.activeTour()?.key).toBe('later');
            expect(consoleError).toHaveBeenCalledExactlyOnceWith(
                expect.stringContaining('Checking whether tour "intro" is available failed'),
                expect.objectContaining({ message: 'The availability check of "intro" failed' })
            );
            consoleError.mockRestore();
        });
    });
});
