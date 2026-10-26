import { TestBed } from '@angular/core/testing';

import { TourRect, TourTargetGeometry } from './tour-target-geometry';

/** Gives an element the box and visibility jsdom cannot compute. */
function layOut(element: Element, rect: TourRect, visible = true): { moveTo(next: TourRect): void } {
    let current = rect;
    Object.assign(element, {
        getBoundingClientRect: () => ({
            ...current,
            right: current.left + current.width,
            bottom: current.top + current.height,
        }),
        checkVisibility: () => visible,
    });
    return {
        moveTo: (next) => {
            current = next;
        },
    };
}

const BOX: TourRect = { top: 100, left: 40, width: 120, height: 32 };

describe('TourTargetGeometry', () => {
    let page: HTMLElement;
    let scrollContainer: HTMLElement;
    let targetElement: HTMLElement;
    let changeCount: number;
    let geometry: TourTargetGeometry;
    let resizeCallbacks: (() => void)[];

    beforeEach(() => {
        vi.useFakeTimers({ toFake: ['requestAnimationFrame', 'cancelAnimationFrame'] });
        resizeCallbacks = [];
        // jsdom has no ResizeObserver; this one lets a spec report a resize.
        vi.stubGlobal(
            'ResizeObserver',
            class {
                constructor(callback: () => void) {
                    resizeCallbacks.push(callback);
                }
                observe(): void {}
                disconnect(): void {}
            }
        );
        page = document.createElement('div');
        scrollContainer = document.createElement('div');
        targetElement = document.createElement('button');
        scrollContainer.appendChild(targetElement);
        page.appendChild(scrollContainer);
        document.body.appendChild(page);
        changeCount = 0;
        geometry = TestBed.runInInjectionContext(() => new TourTargetGeometry(() => changeCount++));
    });

    afterEach(() => {
        geometry.dispose();
        page.remove();
        vi.unstubAllGlobals();
        vi.useRealTimers();
    });

    it('measures the target at once when it starts following it', () => {
        layOut(targetElement, BOX);

        geometry.track(targetElement);

        expect(geometry.rect()).toEqual(BOX);
        expect(changeCount).toBe(0);
    });

    it('follows a target scrolled by a nested container that CDK does not know about, once per frame', () => {
        const layout = layOut(targetElement, BOX);
        geometry.track(targetElement);

        layout.moveTo({ ...BOX, top: 60 });
        scrollContainer.dispatchEvent(new Event('scroll'));
        scrollContainer.dispatchEvent(new Event('scroll'));
        vi.advanceTimersToNextFrame();

        expect(geometry.rect()).toEqual({ ...BOX, top: 60 });
        expect(changeCount).toBe(1);
    });

    it('follows a target that resizes', () => {
        const layout = layOut(targetElement, BOX);
        geometry.track(targetElement);

        layout.moveTo({ ...BOX, height: 64 });
        resizeCallbacks.forEach((callback) => callback());
        vi.advanceTimersToNextFrame();

        expect(geometry.rect()).toEqual({ ...BOX, height: 64 });
    });

    it('notices a target hidden or revealed by a transition, e.g. the phone drawer sliding out and in', () => {
        layOut(targetElement, BOX);
        geometry.track(targetElement);

        scrollContainer.setAttribute('inert', '');
        scrollContainer.dispatchEvent(new Event('transitionend', { bubbles: true }));
        vi.advanceTimersToNextFrame();
        const whileHidden = geometry.rect();

        scrollContainer.removeAttribute('inert');
        scrollContainer.dispatchEvent(new Event('transitionend', { bubbles: true }));
        vi.advanceTimersToNextFrame();

        expect(whileHidden).toBeNull();
        expect(geometry.rect()).toEqual(BOX);
        expect(changeCount).toBe(2);
    });

    it('does not report changes that did not move the target, nor anything after dispose', () => {
        const layout = layOut(targetElement, BOX);
        geometry.track(targetElement);

        scrollContainer.dispatchEvent(new Event('scroll'));
        vi.advanceTimersToNextFrame();
        geometry.dispose();
        layout.moveTo({ ...BOX, top: 0 });
        scrollContainer.dispatchEvent(new Event('scroll'));
        vi.advanceTimersToNextFrame();

        expect(changeCount).toBe(0);
    });
});
