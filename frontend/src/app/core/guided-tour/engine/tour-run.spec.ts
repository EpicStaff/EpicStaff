import { TourContent } from '../model/tour-content';
import { TourDefinition, TourStep } from '../model/tour-definition';
import { TourDefinitionFactory } from '../registry/guided-tour-registry.service';
import { GuidedTourTestbed, setUpGuidedTourTestbed } from '../testing/guided-tour-testing';

const WAIT_MS = 1500;
const LABEL_ATTRIBUTE = 'data-label';

function content(title: string, ...body: string[]): TourContent {
    return { title, body };
}

/** A content function that fails, like a definition with a bug in it. */
function failingContent(): TourContent {
    throw new Error('The content function failed');
}

function tourOf(key: string, steps: TourStep[]): TourDefinitionFactory {
    return (): TourDefinition => ({
        key,
        label: key,
        icon: 'help',
        autoStart: 'manual',
        isAvailable: () => true,
        steps,
    });
}

const TOURS: TourDefinitionFactory[] = [
    tourOf('walk', [
        { id: 'welcome', content: content('Welcome'), buttons: { next: 'Get started', skip: 'Skip' } },
        { id: 'middle', content: content('Middle', 'Look here.'), showProgress: true },
        { id: 'counted', content: content('Counted'), showProgress: true, buttons: { close: false } },
        { id: 'last', content: content('Last') },
    ]),
    tourOf('pointing', [
        {
            id: 'icon',
            content: content('Click the icon'),
            fallbackContent: content('Press Next'),
            target: { anchor: 'icon', side: 'right' },
            floating: 'bottom-start',
        },
    ]),
    tourOf('waiting', [
        { id: 'start', content: content('Start') },
        {
            id: 'late',
            content: (context) => {
                const label = context.targetAttribute(LABEL_ATTRIBUTE);
                return content(label ? `Found ${label}` : 'Not found');
            },
            target: { anchor: 'late', side: 'top', waitMs: WAIT_MS },
        },
    ]),
    tourOf('clicking', [
        {
            id: 'open',
            content: content('Open it'),
            target: { anchor: 'opener', side: 'bottom' },
            advance: { kind: 'target-click', timing: 'after-target' },
            buttons: { next: false },
        },
        {
            id: 'result',
            content: content('Result'),
            target: { anchor: 'card', side: 'left' },
            advance: { kind: 'target-click', timing: 'before-target' },
        },
    ]),
    tourOf('watching', [
        { id: 'before', content: content('Before') },
        {
            id: 'activate',
            content: content('Activate'),
            advance: { kind: 'anchor-appears', anchor: 'result' },
            buttons: { next: false },
        },
        { id: 'done', content: content('Done') },
    ]),
    tourOf('skipping-back', [
        { id: 'pick', content: content('Pick') },
        { id: 'list', content: content('List') },
        { id: 'key', content: content('Key'), back: { toStep: 'pick' } },
    ]),
    tourOf('failing-first', [{ id: 'broken', content: failingContent }]),
    tourOf('failing-later', [
        { id: 'fine', content: content('Fine') },
        { id: 'broken', content: failingContent },
    ]),
];

describe('TourRun', () => {
    let testbed: GuidedTourTestbed;

    beforeEach(() => {
        testbed = setUpGuidedTourTestbed({ tours: TOURS });
    });

    afterEach(() => {
        testbed.cleanUp();
        vi.useRealTimers();
    });

    function view() {
        const shown = testbed.renderer().view;
        if (!shown) {
            throw new Error('No step is shown.');
        }
        return shown;
    }

    /** Lets a MutationObserver see a DOM change. */
    async function domObserved(): Promise<void> {
        await Promise.resolve();
        await Promise.resolve();
    }

    describe('steps', () => {
        it('walks the steps on Next and Back, and finishes after the last one', async () => {
            await testbed.service.start('walk');
            const renderer = testbed.renderer();

            renderer.press('next');
            renderer.press('next');
            expect(view().content.title).toBe('Counted');
            renderer.press('back');
            expect(view().content.title).toBe('Middle');
            renderer.press('next');
            renderer.press('next');
            expect(view().content.title).toBe('Last');
            renderer.press('next');

            expect(renderer.isDisposed).toBe(true);
            expect(testbed.progressStore.savedTourKeys).toEqual(['walk']);
        });

        it.each([
            [
                'the first step: its own labels, no Back',
                0,
                { next: 'Get started', back: false, skip: 'Skip', close: true },
            ],
            ['a middle step: the defaults', 1, { next: 'Next', back: 'Back', skip: false, close: true }],
            ['a step without the close button', 2, { next: 'Next', back: 'Back', skip: false, close: false }],
            ['the last step: Finish', 3, { next: 'Finish', back: 'Back', skip: false, close: true }],
        ])('shows the buttons of %s', async (_step, index, buttons) => {
            await testbed.service.start('walk');
            for (let pressed = 0; pressed < index; pressed++) {
                testbed.renderer().press('next');
            }

            expect(view().buttons).toEqual(buttons);
        });

        it('counts only the steps that show progress', async () => {
            await testbed.service.start('walk');
            const progress = [view().progress];
            for (let pressed = 0; pressed < 3; pressed++) {
                testbed.renderer().press('next');
                progress.push(view().progress);
            }

            expect(progress).toEqual([null, { current: 1, total: 2 }, { current: 2, total: 2 }, null]);
        });

        it('goes Back to the step named by the definition', async () => {
            await testbed.service.start('skipping-back');
            testbed.renderer().press('next');
            testbed.renderer().press('next');

            testbed.renderer().press('back');

            expect(view().content.title).toBe('Pick');
        });
    });

    describe('targets', () => {
        it('points at the anchored element, on the side the step prefers', async () => {
            const icon = testbed.appendAnchor('icon');

            await testbed.service.start('pointing');

            expect(view().target).toBe(icon);
            expect(view().side).toBe('right');
            expect(view().content.title).toBe('Click the icon');
        });

        it('shows the fallback content, still following the element, while the target is hidden (phone)', async () => {
            const icon = testbed.appendAnchor('icon', { hidden: true });

            await testbed.service.start('pointing');

            expect(view().content.title).toBe('Press Next');
            expect(view().target).toBe(icon);
        });

        it('floats with the fallback content when the target is missing', async () => {
            await testbed.service.start('pointing');

            expect(view().content.title).toBe('Press Next');
            expect(view().target).toBeNull();
            expect(view().floating).toBe('bottom-start');
        });

        it('waits for a target that appears later, and points at it', async () => {
            vi.useFakeTimers();
            await testbed.service.start('waiting');
            testbed.renderer().press('next');
            expect(view().content.title).toBe('Start');

            testbed.appendAnchor('late').setAttribute(LABEL_ATTRIBUTE, 'the card');
            await domObserved();

            expect(view().content.title).toBe('Found the card');
            expect(view().side).toBe('top');
        });

        it('shows the left step pending while the next one waits, and the next one live once it shows', async () => {
            vi.useFakeTimers();
            await testbed.service.start('waiting');
            const isPendingAtStart = testbed.renderer().isPending;

            testbed.renderer().press('next');
            const isPendingWhileWaiting = testbed.renderer().isPending;
            await vi.advanceTimersByTimeAsync(WAIT_MS);

            expect([isPendingAtStart, isPendingWhileWaiting]).toEqual([false, true]);
            expect(view().content.title).toBe('Not found');
            expect(testbed.renderer().isPending).toBe(false);
        });

        it('shows the step without a target, centred, once the wait is over', async () => {
            vi.useFakeTimers();
            await testbed.service.start('waiting');
            testbed.renderer().press('next');

            await vi.advanceTimersByTimeAsync(WAIT_MS - 1);
            expect(view().content.title).toBe('Start');
            await vi.advanceTimersByTimeAsync(1);

            expect(view().content.title).toBe('Not found');
            expect(view().target).toBeNull();
            expect(view().floating).toBe('center');
        });

        // Meanwhile the popover still shows the step the tour has left.
        it.each(['next', 'back'] as const)('ignores %s while the next step waits for its target', async (intent) => {
            vi.useFakeTimers();
            await testbed.service.start('waiting');
            testbed.renderer().press('next');

            testbed.renderer().press(intent);
            await vi.advanceTimersByTimeAsync(WAIT_MS);

            expect(view().content.title).toBe('Not found');
        });

        it('still ends on close while the next step waits for its target', async () => {
            vi.useFakeTimers();
            await testbed.service.start('waiting');
            testbed.renderer().press('next');

            testbed.renderer().press('close');

            expect(testbed.renderer().isDisposed).toBe(true);
            expect(testbed.progressStore.savedTourKeys).toEqual(['waiting']);
        });
    });

    describe('advancing', () => {
        it('moves on after the target has handled a click on it', async () => {
            const opener = testbed.appendAnchor('opener');
            const button = opener.appendChild(document.createElement('button'));
            const stepSeenByTarget = vi.fn();
            button.addEventListener('click', () => stepSeenByTarget(testbed.renderer().view?.content.title));
            testbed.appendAnchor('card');
            await testbed.service.start('clicking');

            button.click();

            expect(stepSeenByTarget).toHaveBeenCalledWith('Open it');
            expect(view().content.title).toBe('Result');
        });

        it('moves on after a click in the target even when a re-render replaced it since the step showed', async () => {
            const opener = testbed.appendAnchor('opener');
            testbed.appendAnchor('card');
            await testbed.service.start('clicking');

            opener.remove();
            testbed.appendAnchor('opener').appendChild(document.createElement('button')).click();

            expect(view().content.title).toBe('Result');
        });

        it('does not move on for a click outside the target', async () => {
            testbed.appendAnchor('opener');
            const elsewhere = testbed.appendAnchor('elsewhere');
            await testbed.service.start('clicking');

            elsewhere.click();

            expect(view().content.title).toBe('Open it');
        });

        it('finishes before a control in the target handles a click on the last step, and lets the click through', async () => {
            testbed.appendAnchor('opener');
            const card = testbed.appendAnchor('card');
            const button = card.appendChild(document.createElement('button'));
            const tourEndedBeforeHandler = vi.fn();
            button.addEventListener('click', () => tourEndedBeforeHandler(testbed.renderer().isDisposed));
            await testbed.service.start('clicking');
            testbed.renderer().press('next');

            button.click();
            button.click();

            expect(tourEndedBeforeHandler.mock.calls).toEqual([[true], [true]]);
            expect(testbed.progressStore.savedTourKeys).toEqual(['clicking']);
        });

        it('finishes before the control handles the click also in a target re-rendered since the step showed', async () => {
            testbed.appendAnchor('opener');
            const card = testbed.appendAnchor('card');
            await testbed.service.start('clicking');
            testbed.renderer().press('next');
            card.remove();
            const button = testbed.appendAnchor('card').appendChild(document.createElement('button'));
            const tourEndedBeforeHandler = vi.fn();
            button.addEventListener('click', () => tourEndedBeforeHandler(testbed.renderer().isDisposed));

            button.click();

            expect(tourEndedBeforeHandler).toHaveBeenCalledExactlyOnceWith(true);
        });

        it('moves on once the watched anchor appears, however long that takes', async () => {
            await testbed.service.start('watching');
            testbed.renderer().press('next');
            await domObserved();
            expect(view().content.title).toBe('Activate');

            testbed.appendAnchor('result');
            await domObserved();

            expect(view().content.title).toBe('Done');
        });

        it('stops watching for the anchor once the step is left', async () => {
            await testbed.service.start('watching');
            testbed.renderer().press('next');
            testbed.renderer().press('back');

            testbed.appendAnchor('result');
            await domObserved();

            expect(view().content.title).toBe('Before');
        });
    });

    describe('a step that fails', () => {
        it.each([
            ['the first step', 'failing-first', 0],
            ['a later step', 'failing-later', 1],
        ])('on %s, logs, ends the tour unsaved, and lets the next tour start', async (_step, key, nextPresses) => {
            const consoleError = vi.spyOn(console, 'error').mockImplementation(() => undefined);
            await testbed.service.start(key);
            for (let pressed = 0; pressed < nextPresses; pressed++) {
                testbed.renderer().press('next');
            }

            expect(testbed.service.activeTour()).toBeNull();
            expect(testbed.renderer().isDisposed).toBe(true);
            expect(testbed.progressStore.savedTourKeys).toEqual([]);
            expect(consoleError).toHaveBeenCalled();
            consoleError.mockRestore();

            await testbed.service.start('walk');
            expect(view().content.title).toBe('Welcome');
        });

        it('ends the tour unsaved, and logs, when something the step watches errors', async () => {
            const consoleError = vi.spyOn(console, 'error').mockImplementation(() => undefined);
            await testbed.service.start('watching');
            // The next step watches the DOM for its anchor; here the watch cannot start.
            vi.stubGlobal(
                'MutationObserver',
                class {
                    constructor() {
                        throw new Error('The DOM cannot be watched');
                    }
                }
            );

            testbed.renderer().press('next');
            vi.unstubAllGlobals();

            expect(testbed.service.activeTour()).toBeNull();
            expect(testbed.renderer().isDisposed).toBe(true);
            expect(testbed.progressStore.savedTourKeys).toEqual([]);
            expect(consoleError).toHaveBeenCalledWith(
                expect.stringContaining('failed on step "activate"'),
                expect.objectContaining({ message: 'The DOM cannot be watched' })
            );
            consoleError.mockRestore();
        });
    });
});
