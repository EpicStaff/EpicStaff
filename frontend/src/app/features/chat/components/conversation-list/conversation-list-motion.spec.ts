import { AnimationCallbackEvent } from '@angular/core';

import { ConversationListMotion, ConversationListMotionOptions } from './conversation-list-motion';

type VoidMock = ReturnType<typeof vi.fn<() => void>>;

interface FakeAnimation {
    onfinish: (() => void) | null;
    oncancel: (() => void) | null;
    finished: Promise<void>;
    cancel: VoidMock;
    finish: VoidMock;
}

function fakeAnimation(): FakeAnimation {
    let resolveFinished: () => void = () => undefined;
    let rejectFinished: (reason: unknown) => void = () => undefined;
    const finished = new Promise<void>((resolve, reject) => {
        resolveFinished = resolve;
        rejectFinished = reject;
    });
    // A cancelled animation's `finished` rejects; nobody may be waiting on it.
    finished.catch(() => undefined);
    const animation: FakeAnimation = {
        onfinish: null,
        oncancel: null,
        finished,
        cancel: vi.fn<() => void>(() => {
            rejectFinished(new DOMException('Cancelled', 'AbortError'));
            animation.oncancel?.();
        }),
        finish: vi.fn<() => void>(() => {
            resolveFinished();
            animation.onfinish?.();
        }),
    };
    return animation;
}

type MotionRow = HTMLLIElement & { animate: ReturnType<typeof vi.fn>; scrollIntoView: ReturnType<typeof vi.fn> };

/** A row as the column renders it: an `li` keyed by the conversation id. */
function row(id: string): MotionRow {
    const element = document.createElement('li');
    element.dataset['id'] = id;
    Object.assign(element, { animate: vi.fn(() => fakeAnimation()), scrollIntoView: vi.fn() });
    return element as MotionRow;
}

/** A row on screen at a fixed `top`. */
function rowAt(id: string, top: number): MotionRow {
    const element = row(id);
    element.getBoundingClientRect = () => ({ top }) as DOMRect;
    document.body.append(element);
    return element;
}

/** A list laid out like the column: each row 60px under the previous one in the flow (not hidden, not lifted out). */
function column(): { list: HTMLUListElement; add: (id: string) => MotionRow } {
    const list = document.createElement('ul');
    document.body.append(list);
    const inLayout = (): Element[] =>
        [...list.children].filter(
            (item) =>
                (item as HTMLElement).style.display !== 'none' && (item as HTMLElement).style.position !== 'absolute'
        );
    const add = (id: string): MotionRow => {
        const element = row(id);
        element.getBoundingClientRect = () => ({ top: 60 * inLayout().indexOf(element) }) as DOMRect;
        list.append(element);
        return element;
    };
    return { list, add };
}

const slideOf = (element: MotionRow): unknown => element.animate.mock.calls[0]?.[0];

const moveTo = (row: HTMLElement, top: number): void => {
    row.getBoundingClientRect = () => ({ top }) as DOMRect;
};

function callbackEvent(target: Element): AnimationCallbackEvent & { animationComplete: VoidMock } {
    return { target, animationComplete: vi.fn<() => void>() };
}

describe('ConversationListMotion', () => {
    let reducedMotion: boolean;
    let shown: Set<string>;
    let options: ConversationListMotionOptions & {
        restoreFocus: ReturnType<typeof vi.fn<(id: string) => void>>;
        focusSectionHeader: ReturnType<typeof vi.fn<(section: string) => void>>;
    };
    let motion: ConversationListMotion;

    beforeEach(() => {
        reducedMotion = false;
        shown = new Set();
        options = {
            prefersReducedMotion: () => reducedMotion,
            isShown: (id) => shown.has(id),
            restoreFocus: vi.fn<(id: string) => void>(),
            focusSectionHeader: vi.fn<(section: string) => void>(),
        };
        motion = new ConversationListMotion(options);
    });

    afterEach(() => document.body.replaceChildren());

    describe('moves', () => {
        it('slides a row a live change moved, from where it was to its new place', () => {
            const row = rowAt('c-1', 100);
            expect(motion.note('live', () => [row])).toBe(true);
            moveTo(row, 40);
            motion.play([row]);

            expect(row.animate).toHaveBeenCalledTimes(1);
            expect(row.animate).toHaveBeenCalledWith(
                [{ transform: 'translateY(60px)' }, { transform: 'none' }],
                expect.objectContaining({ duration: 280 })
            );
        });

        it('leaves a row that kept its place alone', () => {
            const row = rowAt('c-1', 100);
            motion.note('live', () => [row]);
            motion.play([row]);
            expect(row.animate).not.toHaveBeenCalled();
        });

        it('moves nothing for a load change, nor for a batch a load joined', () => {
            const row = rowAt('c-1', 100);
            const measured = vi.fn(() => [row]);
            motion.note('load', measured);
            moveTo(row, 40);
            motion.play([row]);
            expect(measured).not.toHaveBeenCalled();
            expect(row.animate).not.toHaveBeenCalled();

            moveTo(row, 100);
            expect(motion.note('live', () => [row])).toBe(true);
            expect(motion.note('load', () => [row])).toBe(false);
            moveTo(row, 40);
            motion.play([row]);
            expect(row.animate).not.toHaveBeenCalled();
        });

        it('takes every change before a render as one batch, measured once', () => {
            const row = rowAt('c-1', 100);
            const measured = vi.fn(() => [row]);
            expect(motion.note('live', measured)).toBe(true);
            expect(motion.note('live', measured)).toBe(false);
            expect(measured).toHaveBeenCalledTimes(1);
            motion.play([row]);
            expect(motion.note('live', measured)).toBe(true);
        });

        it('cancels a slide still running before measuring the next one, so transforms never stack', () => {
            const row = rowAt('c-1', 100);
            motion.note('live', () => [row]);
            moveTo(row, 40);
            motion.play([row]);
            const first = row.animate.mock.results[0].value as FakeAnimation;

            motion.note('live', () => [row]);
            moveTo(row, 160);
            motion.play([row]);
            expect(first.cancel).toHaveBeenCalled();
            expect(row.animate).toHaveBeenLastCalledWith(
                [{ transform: 'translateY(-120px)' }, { transform: 'none' }],
                expect.anything()
            );
        });
    });

    describe('arrivals and departures', () => {
        it('fades in a row a live change brought from outside the shown rows', () => {
            const before = rowAt('c-1', 100);
            motion.note('live', () => [before]);
            const arrived = rowAt('c-9', 40);
            motion.enter(callbackEvent(arrived), 'c-9');
            expect(arrived.animate).toHaveBeenCalledWith(
                [expect.objectContaining({ opacity: 0 }), expect.objectContaining({ opacity: 1 })],
                expect.objectContaining({ duration: 220 })
            );
        });

        it('skips the enter and the leave of a row that moved between sections: its slide covers it', () => {
            const old = rowAt('c-1', 100);
            motion.note('live', () => [old]);
            shown.add('c-1');

            const leaving = callbackEvent(old);
            motion.leave(leaving, 'c-1');
            expect(leaving.animationComplete).toHaveBeenCalled();
            expect(old.animate).not.toHaveBeenCalled();
            // Out of the layout at once: Angular removes it only after the slides are measured.
            expect(old.style.display).toBe('none');

            const recreated = rowAt('c-1', 300);
            motion.enter(callbackEvent(recreated), 'c-1');
            expect(recreated.animate).not.toHaveBeenCalled();
        });

        it('fades out a row a live change took out of the shown rows, out of the flow, and removes it after', () => {
            const row = rowAt('c-1', 100);
            motion.note('live', () => [row]);
            const event = callbackEvent(row);
            motion.leave(event, 'c-1');

            expect(row.animate).toHaveBeenCalledWith(
                [expect.objectContaining({ opacity: 1 }), expect.objectContaining({ opacity: 0 })],
                expect.objectContaining({ duration: 180 })
            );
            expect(row.style.position).toBe('absolute');
            expect(event.animationComplete).not.toHaveBeenCalled();

            (row.animate.mock.results[0].value as FakeAnimation).finish();
            expect(event.animationComplete).toHaveBeenCalledTimes(1);
        });

        it('lets rows come and go at once outside a live batch', () => {
            const row = rowAt('c-1', 100);
            motion.enter(callbackEvent(row), 'c-1');
            const event = callbackEvent(row);
            motion.leave(event, 'c-1');
            expect(row.animate).not.toHaveBeenCalled();
            expect(event.animationComplete).toHaveBeenCalled();

            motion.note('load', () => [row]);
            motion.enter(callbackEvent(row), 'c-2');
            expect(row.animate).not.toHaveBeenCalled();
        });
    });

    it('animates nothing at all under reduced motion', () => {
        reducedMotion = true;
        const row = rowAt('c-1', 100);
        motion.note('live', () => [row]);
        moveTo(row, 40);
        motion.play([row]);
        const arrived = rowAt('c-9', 0);
        motion.enter(callbackEvent(arrived), 'c-9');
        const event = callbackEvent(row);
        motion.leave(event, 'c-1');

        expect(row.animate).not.toHaveBeenCalled();
        expect(arrived.animate).not.toHaveBeenCalled();
        expect(event.animationComplete).toHaveBeenCalled();
    });

    describe('a move as a browser renders it: the old element is still in the document when play runs', () => {
        let rows: ReturnType<typeof column>;
        let old: MotionRow;
        let second: MotionRow;
        let third: MotionRow;
        let recreated: MotionRow;

        /** c-1 moves from the top to the end: re-created there, its old element left until its leave settles. */
        function moveFirstToEnd(): void {
            rows = column();
            old = rows.add('c-1');
            second = rows.add('c-2');
            third = rows.add('c-3');
            const button = document.createElement('button');
            old.append(button);
            button.focus();
            motion.note('live', () => [old, second, third]);

            recreated = rows.add('c-1');
            shown.add('c-1');
            motion.enter(callbackEvent(recreated), 'c-1');
            motion.leave(callbackEvent(old), 'c-1');
            expect(old.isConnected).toBe(true);
            motion.play([second, third, recreated]);
        }

        it('slides the rows below by one row and the moved row from its old place', () => {
            moveFirstToEnd();
            expect(slideOf(second)).toEqual([{ transform: 'translateY(60px)' }, { transform: 'none' }]);
            expect(slideOf(third)).toEqual([{ transform: 'translateY(60px)' }, { transform: 'none' }]);
            expect(slideOf(recreated)).toEqual([{ transform: 'translateY(-120px)' }, { transform: 'none' }]);
        });

        it('gives the focus to the new row and brings it into view once it has slid', async () => {
            moveFirstToEnd();
            expect(options.restoreFocus).toHaveBeenCalledWith('c-1');
            expect(recreated.scrollIntoView).not.toHaveBeenCalled();

            (recreated.animate.mock.results[0].value as FakeAnimation).finish();
            await Promise.resolve();
            expect(recreated.scrollIntoView).toHaveBeenCalledWith({ block: 'nearest' });
        });

        it('brings the focused row into view at once under reduced motion', () => {
            reducedMotion = true;
            moveFirstToEnd();
            expect(recreated.animate).not.toHaveBeenCalled();
            expect(options.restoreFocus).toHaveBeenCalledWith('c-1');
            expect(recreated.scrollIntoView).toHaveBeenCalledWith({ block: 'nearest' });
        });
    });

    describe('focus on a row that leaves the shown rows', () => {
        let rows: ReturnType<typeof column>;

        /** c-1, c-2 and c-3 in one section, the focus inside `focusedId`; then the rows in `gone` leave for good. */
        function leave(focusedId: string, gone: string[]): Map<string, MotionRow> {
            rows = column();
            const section = document.createElement('section');
            section.dataset['section'] = 'in_progress';
            section.append(rows.list);
            document.body.append(section);
            const byId = new Map(['c-1', 'c-2', 'c-3'].map((id) => [id, rows.add(id)]));
            const button = document.createElement('button');
            byId.get(focusedId)!.append(button);
            button.focus();
            ['c-1', 'c-2', 'c-3'].filter((id) => !gone.includes(id)).forEach((id) => shown.add(id));
            motion.note('live', () => byId.values());
            // As a browser renders it: each fades out while still in the document, and play runs during the fade.
            for (const id of gone) motion.leave(callbackEvent(byId.get(id)!), id);
            motion.play([...byId.values()].filter((row) => !gone.includes(row.dataset['id']!)));
            return byId;
        }

        it('hands the focus to the next shown row, brought into view once it has slid up', async () => {
            const byId = leave('c-2', ['c-2']);
            expect(options.restoreFocus).toHaveBeenCalledWith('c-3');
            expect(byId.get('c-3')!.scrollIntoView).not.toHaveBeenCalled();

            (byId.get('c-3')!.animate.mock.results[0].value as FakeAnimation).finish();
            await Promise.resolve();
            expect(byId.get('c-3')!.scrollIntoView).toHaveBeenCalledWith({ block: 'nearest' });
        });

        it('hands it to the previous shown row when none follows', () => {
            leave('c-3', ['c-3', 'c-2']);
            expect(options.restoreFocus).toHaveBeenCalledWith('c-1');
            expect(options.focusSectionHeader).not.toHaveBeenCalled();
        });

        it("hands it to the section's header when no row is left", () => {
            leave('c-1', ['c-1', 'c-2', 'c-3']);
            expect(options.restoreFocus).not.toHaveBeenCalled();
            expect(options.focusSectionHeader).toHaveBeenCalledWith('in_progress');
        });

        it('leaves the focus alone when it was not on a row that left', () => {
            leave('c-1', ['c-2']);
            expect(options.restoreFocus).not.toHaveBeenCalled();
            expect(options.focusSectionHeader).not.toHaveBeenCalled();
        });
    });

    describe('focus', () => {
        it('gives a moved row its focus back once its element was re-created, its old one already gone', () => {
            const row = rowAt('c-1', 100);
            const button = document.createElement('button');
            row.append(button);
            button.focus();
            motion.note('live', () => [row]);
            row.remove();
            shown.add('c-1');
            motion.play([rowAt('c-1', 300)]);
            expect(options.restoreFocus).toHaveBeenCalledWith('c-1');
        });

        it('leaves the focus alone when its element stayed', () => {
            const row = rowAt('c-1', 100);
            const button = document.createElement('button');
            row.append(button);
            button.focus();
            shown.add('c-1');
            motion.note('live', () => [row]);
            motion.play([row]);
            expect(options.restoreFocus).not.toHaveBeenCalled();
            expect(options.focusSectionHeader).not.toHaveBeenCalled();
        });

        it('also restores it under reduced motion: focus is not motion', () => {
            reducedMotion = true;
            const row = rowAt('c-1', 100);
            const button = document.createElement('button');
            row.append(button);
            button.focus();
            motion.note('live', () => [row]);
            row.remove();
            shown.add('c-1');
            motion.play([]);
            expect(options.restoreFocus).toHaveBeenCalledWith('c-1');
        });
    });

    it('finishes everything still running when the column goes away or the rows are reloaded', () => {
        const row = rowAt('c-1', 100);
        motion.note('live', () => [row]);
        moveTo(row, 40);
        motion.play([row]);
        const slide = row.animate.mock.results[0].value as FakeAnimation;

        const leaving = rowAt('c-2', 200);
        motion.note('live', () => [row, leaving]);
        const event = callbackEvent(leaving);
        motion.leave(event, 'c-2');
        motion.play([row]);

        motion.destroy();
        expect(event.animationComplete).toHaveBeenCalled();
        expect(slide.cancel.mock.calls.length + slide.finish.mock.calls.length).toBeGreaterThan(0);

        const again = rowAt('c-3', 100);
        motion.note('live', () => [again]);
        moveTo(again, 40);
        motion.play([again]);
        const running = again.animate.mock.results[0].value as FakeAnimation;
        motion.note('load', () => [again]);
        expect(running.finish).toHaveBeenCalled();
    });
});
