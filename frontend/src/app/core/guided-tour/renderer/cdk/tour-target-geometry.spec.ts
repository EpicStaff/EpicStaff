import { TestBed } from '@angular/core/testing';

import { TourRect, TourTargetGeometry } from './tour-target-geometry';

/** What a browser's checkVisibility() reports hidden; jsdom computes no styles, so the specs hide with these. */
const HIDDEN_BY_DOM = '[hidden], .collapsed, [style*="visibility: hidden"]';

interface Layout {
    moveTo(next: TourRect): void;
    /** Hides or shows the element without touching the DOM, like a style sheet that starts to apply. */
    setVisible(visible: boolean): void;
}

/** Gives an element the box and visibility jsdom cannot compute. */
function layOut(element: Element, rect: TourRect): Layout {
    let current = rect;
    let visible = true;
    Object.assign(element, {
        getBoundingClientRect: () => ({
            ...current,
            right: current.left + current.width,
            bottom: current.top + current.height,
        }),
        checkVisibility: () => visible && !element.closest(HIDDEN_BY_DOM),
    });
    return {
        moveTo: (next) => {
            current = next;
        },
        setVisible: (next) => {
            visible = next;
        },
    };
}

const BOX: TourRect = { top: 100, left: 40, width: 120, height: 32 };

/** Lets attribute changes reach the geometry: MutationObserver reports them in a microtask. */
async function flushMutations(): Promise<void> {
    await Promise.resolve();
}

/** jsdom has no ResizeObserver; this one remembers what it observes, so a spec can report an element's resize. */
class FakeResizeObserver {
    static readonly instances: FakeResizeObserver[] = [];
    private readonly observed = new Set<Element>();

    constructor(private readonly callback: () => void) {
        FakeResizeObserver.instances.push(this);
    }

    /** What the browser does when `element` changes size. */
    static reportResize(element: Element): void {
        FakeResizeObserver.instances
            .filter((observer) => observer.observed.has(element))
            .forEach((observer) => observer.callback());
    }

    observe(element: Element): void {
        this.observed.add(element);
    }

    disconnect(): void {
        this.observed.clear();
    }
}

describe('TourTargetGeometry', () => {
    let page: HTMLElement;
    let scrollContainer: HTMLElement;
    let section: HTMLElement;
    let targetElement: HTMLElement;
    let changeCount: number;
    let geometry: TourTargetGeometry;

    /** Runs the frames measured after a step starts, so a spec sees only what its own event makes the geometry do. */
    function letLayoutSettle(): void {
        vi.advanceTimersByTime(5000);
    }

    beforeEach(() => {
        vi.useFakeTimers({ toFake: ['requestAnimationFrame', 'cancelAnimationFrame', 'performance'] });
        FakeResizeObserver.instances.length = 0;
        vi.stubGlobal('ResizeObserver', FakeResizeObserver);
        // page > scroll container > section (as tall as its content) > target
        page = document.createElement('div');
        scrollContainer = document.createElement('div');
        scrollContainer.style.overflowY = 'auto';
        section = document.createElement('section');
        targetElement = document.createElement('button');
        section.appendChild(targetElement);
        scrollContainer.appendChild(section);
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

    it('keeps measuring on every frame for a short while after a step starts, e.g. while a page is still laid out', () => {
        const layout = layOut(targetElement, BOX);
        geometry.track(targetElement);

        // Most of half a second in, as when an image above the target loads.
        vi.advanceTimersByTime(400);
        layout.moveTo({ ...BOX, top: 160 });
        vi.advanceTimersToNextFrame();
        const whileSettling = geometry.rect();
        letLayoutSettle();
        layout.moveTo({ ...BOX, top: 220 });
        letLayoutSettle();

        expect(whileSettling).toEqual({ ...BOX, top: 160 });
        // Once settled, a move nothing reports goes unnoticed: the geometry does not poll for good.
        expect(geometry.rect()).toEqual({ ...BOX, top: 160 });
    });

    it('follows a target scrolled by a nested container that CDK does not know about, once per frame', () => {
        const layout = layOut(targetElement, BOX);
        geometry.track(targetElement);
        letLayoutSettle();

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
        letLayoutSettle();

        layout.moveTo({ ...BOX, height: 64 });
        FakeResizeObserver.reportResize(targetElement);
        vi.advanceTimersToNextFrame();

        expect(geometry.rect()).toEqual({ ...BOX, height: 64 });
    });

    it.each<[resized: string, targetScrolls: boolean, resizedElement: () => HTMLElement]>([
        ['the section around it grows', false, () => section],
        ['its scroll container shrinks, e.g. a banner above it', false, () => scrollContainer],
        ['the section around a target that scrolls itself grows, e.g. a dropdown list', true, () => section],
    ])('follows a target moved without a scroll when %s', (_resized, targetScrolls, resizedElement) => {
        if (targetScrolls) {
            targetElement.style.overflowY = 'auto';
        }
        const layout = layOut(targetElement, BOX);
        geometry.track(targetElement);
        letLayoutSettle();

        // Content loaded above the target pushes it down.
        layout.moveTo({ ...BOX, top: 180 });
        FakeResizeObserver.reportResize(resizedElement());
        vi.advanceTimersToNextFrame();

        expect(geometry.rect()).toEqual({ ...BOX, top: 180 });
        expect(changeCount).toBe(1);
    });

    it.each(['transitionend', 'animationend'])(
        'notices a target hidden or revealed when a %s event ends a slide, e.g. the phone drawer sliding out and in',
        (eventName) => {
            const layout = layOut(targetElement, BOX);
            geometry.track(targetElement);
            letLayoutSettle();

            layout.setVisible(false);
            scrollContainer.dispatchEvent(new Event(eventName, { bubbles: true }));
            vi.advanceTimersToNextFrame();
            const whileHidden = geometry.rect();

            layout.setVisible(true);
            scrollContainer.dispatchEvent(new Event(eventName, { bubbles: true }));
            vi.advanceTimersToNextFrame();

            expect(whileHidden).toBeNull();
            expect(geometry.rect()).toEqual(BOX);
            expect(changeCount).toBe(2);
        }
    );

    it('follows a target its overlay pane moves without resizing it, e.g. a dropdown CDK positions once rendered', async () => {
        const boundingBox = document.createElement('div');
        boundingBox.className = 'cdk-overlay-connected-position-bounding-box';
        const pane = document.createElement('div');
        pane.className = 'cdk-overlay-pane';
        const list = document.createElement('ul');
        pane.appendChild(list);
        boundingBox.appendChild(pane);
        page.appendChild(boundingBox);
        // Rendered at the corner of the overlay container, before CDK has positioned the pane.
        const layout = layOut(list, { top: 0, left: 0, width: 200, height: 160 });
        geometry.track(list);
        letLayoutSettle();

        layout.moveTo({ top: 254, left: 287, width: 200, height: 160 });
        boundingBox.style.top = '254px';
        pane.style.left = '287px';
        await flushMutations();
        vi.advanceTimersToNextFrame();

        expect(geometry.rect()).toEqual({ top: 254, left: 287, width: 200, height: 160 });
        expect(changeCount).toBe(1);
    });

    it.each<[change: string, hide: (ancestor: HTMLElement) => void, reveal: (ancestor: HTMLElement) => void]>([
        [
            'inert taken off',
            (ancestor) => ancestor.setAttribute('inert', ''),
            (ancestor) => ancestor.removeAttribute('inert'),
        ],
        [
            'hidden taken off',
            (ancestor) => ancestor.setAttribute('hidden', ''),
            (ancestor) => ancestor.removeAttribute('hidden'),
        ],
        [
            'a class taken off',
            (ancestor) => ancestor.classList.add('collapsed'),
            (ancestor) => ancestor.classList.remove('collapsed'),
        ],
        [
            'an inline style changed',
            (ancestor) => (ancestor.style.visibility = 'hidden'),
            (ancestor) => (ancestor.style.visibility = ''),
        ],
    ])(
        'notices a target revealed by %s on an ancestor, with no transition, scroll or resize',
        async (_change, hide, reveal) => {
            layOut(targetElement, BOX);
            hide(scrollContainer);
            geometry.track(targetElement);
            letLayoutSettle();
            const whileHidden = geometry.rect();

            reveal(scrollContainer);
            await flushMutations();
            vi.advanceTimersToNextFrame();

            expect(whileHidden).toBeNull();
            expect(geometry.rect()).toEqual(BOX);
            expect(changeCount).toBe(1);
        }
    );

    it('does not report changes that did not move the target, nor anything after dispose', async () => {
        const layout = layOut(targetElement, BOX);
        geometry.track(targetElement);

        scrollContainer.dispatchEvent(new Event('scroll'));
        letLayoutSettle();
        geometry.dispose();
        layout.moveTo({ ...BOX, top: 0 });
        scrollContainer.dispatchEvent(new Event('scroll'));
        scrollContainer.setAttribute('inert', '');
        await flushMutations();
        letLayoutSettle();

        expect(changeCount).toBe(0);
    });
});
