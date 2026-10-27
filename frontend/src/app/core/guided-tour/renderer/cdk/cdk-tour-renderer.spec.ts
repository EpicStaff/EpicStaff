import { Overlay, OverlayConfig } from '@angular/cdk/overlay';
import { EnvironmentInjector } from '@angular/core';
import { TestBed } from '@angular/core/testing';

import { TourFloatingPosition } from '../../model/tour-content';
import { TourRenderer, TourStepView } from '../tour-renderer';
import { createCdkTourRenderer } from './cdk-tour-renderer';

const WELCOME: TourStepView = {
    content: { title: 'Welcome', body: [] },
    target: null,
    side: 'bottom',
    floating: 'center',
    buttons: { next: 'Next', back: false, skip: false, close: true },
    progress: null,
};

const VIEWPORT_MARGIN = 8;

interface Box {
    readonly left: number;
    readonly top: number;
    readonly width: number;
    readonly height: number;
}

// jsdom has no ResizeObserver; app-button's overflow directive only needs it to exist.
class ResizeObserverStub {
    observe(): void {}
    unobserve(): void {}
    disconnect(): void {}
}

describe('CdkTourRenderer', () => {
    let renderer: TourRenderer | null = null;

    beforeEach(() => vi.stubGlobal('ResizeObserver', ResizeObserverStub));

    afterEach(() => {
        renderer?.dispose();
        renderer = null;
        document.querySelectorAll('[data-spec-target]').forEach((element) => element.remove());
        Reflect.deleteProperty(document.documentElement, 'clientWidth');
        Reflect.deleteProperty(document.documentElement, 'clientHeight');
        vi.unstubAllGlobals();
        vi.restoreAllMocks();
        vi.useRealTimers();
    });

    function startRenderer(): TourRenderer {
        renderer = createCdkTourRenderer(TestBed.inject(EnvironmentInjector));
        return renderer;
    }

    /** Sizes the viewport as both the tour (window) and CDK's positioning (the document element) read it. */
    function resizeViewport(width: number, height: number): void {
        vi.stubGlobal('innerWidth', width);
        vi.stubGlobal('innerHeight', height);
        Object.defineProperty(document.documentElement, 'clientWidth', { configurable: true, get: () => width });
        Object.defineProperty(document.documentElement, 'clientHeight', { configurable: true, get: () => height });
    }

    /** A visible element at `box` on the page, which jsdom cannot lay out; `moveTo` lays it out elsewhere. */
    function appendTarget(box: Box): { target: HTMLElement; moveTo(next: Box): void } {
        let current = box;
        const target = document.createElement('button');
        target.setAttribute('data-spec-target', '');
        Object.assign(target, {
            getBoundingClientRect: () => ({
                ...current,
                right: current.left + current.width,
                bottom: current.top + current.height,
            }),
            checkVisibility: () => true,
        });
        document.body.appendChild(target);
        return {
            target,
            moveTo: (next) => {
                current = next;
            },
        };
    }

    /**
     * Makes every element report its content as `contentHeight` tall in a box `boxHeight` tall: jsdom lays nothing out.
     * Elements also get a box, which CDK's InteractivityChecker needs to count them as Tab stops.
     */
    function layOutContent(contentHeight: number, boxHeight: number): void {
        vi.spyOn(HTMLElement.prototype, 'scrollHeight', 'get').mockReturnValue(contentHeight);
        vi.spyOn(HTMLElement.prototype, 'clientHeight', 'get').mockReturnValue(boxHeight);
        vi.spyOn(HTMLElement.prototype, 'getClientRects').mockReturnValue({ length: 1 } as DOMRectList);
    }

    /** Presses Tab from the focused element until the focus comes back, and returns each element it stopped at. */
    function tabStops(): Element[] {
        const start = document.activeElement;
        const stops: Element[] = [];
        for (let press = 0; press < 10; press++) {
            const focused = document.activeElement ?? document.body;
            focused.dispatchEvent(new KeyboardEvent('keydown', { key: 'Tab', bubbles: true, cancelable: true }));
            if (document.activeElement === start || document.activeElement === stops[0]) {
                break;
            }
            if (document.activeElement) {
                stops.push(document.activeElement);
            }
        }
        return stops;
    }

    /** Gives the tour's card the size a browser would lay it out at, so CDK can position it. */
    function layOutCard(size: { width: number; height: number }): void {
        const measure = Element.prototype.getBoundingClientRect;
        vi.spyOn(Element.prototype, 'getBoundingClientRect').mockImplementation(function (this: Element) {
            if (this.classList.contains('cdk-overlay-pane') && this.querySelector('app-tour-popover')) {
                const { width, height } = size;
                return { x: 0, y: 0, top: 0, left: 0, width, height, right: width, bottom: height, toJSON: () => ({}) };
            }
            return measure.call(this);
        });
    }

    function card(): HTMLElement {
        const element = document.querySelector<HTMLElement>('app-tour-popover [role="dialog"]');
        if (!element) {
            throw new Error('No tour card');
        }
        return element;
    }

    /** Where CDK put the card's pane, in viewport coordinates. */
    function cardPaneBox(width: number): { left: number; right: number } {
        const pane = card().closest<HTMLElement>('.cdk-overlay-pane');
        if (!pane) {
            throw new Error('No tour pane');
        }
        const translateX = Number(/translateX\((-?[\d.]+)px\)/.exec(pane.style.transform)?.[1] ?? 0);
        const left = pane.style.left
            ? parseFloat(pane.style.left)
            : document.documentElement.clientWidth - parseFloat(pane.style.right) - width;
        return { left: left + translateX, right: left + translateX + width };
    }

    /** Real CDK overlays, except that the given one (1-based, in creation order) fails to attach its content. */
    function failAttachingOverlay(failingOverlay: number): void {
        const overlay = TestBed.inject(Overlay);
        const createOverlay = overlay.create.bind(overlay);
        let createdOverlays = 0;
        vi.spyOn(overlay, 'create').mockImplementation((config?: OverlayConfig) => {
            const overlayRef = createOverlay(config);
            createdOverlays++;
            if (createdOverlays === failingOverlay) {
                vi.spyOn(overlayRef, 'attach').mockImplementation(() => {
                    throw new Error('The overlay content could not be attached');
                });
            }
            return overlayRef;
        });
    }

    it('leaves no dimmed layer behind when the popover fails to attach after the spotlight', () => {
        // The spotlight overlay is created first, the popover's second.
        failAttachingOverlay(2);
        const failingRenderer = startRenderer();

        expect(() => failingRenderer.show(WELCOME)).toThrow('The overlay content could not be attached');

        expect(document.querySelector('app-tour-spotlight')).toBeNull();
        expect(() => failingRenderer.dispose()).not.toThrow();
    });

    it.each<[placement: string, floating: TourFloatingPosition, maxWidth: string, maxHeight: string]>([
        // Clear of the collapsed app navigation (60px) and 24px above the bottom, with the margin on the far sides.
        ['next to the app navigation at the bottom', 'bottom-start', '1212px', '468px'],
        ['in the middle', 'center', '1264px', '484px'],
    ])(
        'keeps a card floating %s within the viewport, so a short window scrolls its text instead of cutting it off',
        (_placement, floating, maxWidth, maxHeight) => {
            resizeViewport(1280, 500);

            startRenderer().show({ ...WELCOME, floating });

            expect(card().style.maxWidth).toBe(maxWidth);
            expect(card().style.maxHeight).toBe(maxHeight);
        }
    );

    it.each<[where: string, inOverlayPane: boolean, cardLeft: number]>([
        // The target ends at 132; its hole 8px further; the card 12px past the hole.
        ['on the page', false, 152],
        // A target in a dropdown has a hole fitted to it, so the card is 12px past the target itself.
        ['in an overlay pane', true, 144],
    ])('places a card 12px off the hole of a target %s when there is room', (_where, inOverlayPane, cardLeft) => {
        resizeViewport(1280, 800);
        layOutCard({ width: 324, height: 150 });
        const { target } = appendTarget({ left: 100, top: 300, width: 32, height: 32 });
        if (inOverlayPane) {
            const pane = document.createElement('div');
            pane.className = 'cdk-overlay-pane';
            pane.setAttribute('data-spec-target', '');
            document.body.appendChild(pane);
            pane.appendChild(target);
        }

        startRenderer().show({ ...WELCOME, target, side: 'right' });

        expect(cardPaneBox(324).left).toBe(cardLeft);
    });

    it('keeps a card next to its target within the viewport margins, as narrow as a phone', () => {
        resizeViewport(390, 800);
        layOutCard({ width: 324, height: 150 });
        // The Settings icon in the 60px app navigation: no room for the card on its right.
        const { target } = appendTarget({ left: 18, top: 300, width: 32, height: 32 });

        startRenderer().show({ ...WELCOME, target, side: 'right' });

        const pane = cardPaneBox(324);
        expect(card().style.maxWidth).toBe('374px');
        expect(card().style.maxHeight).toBe('784px');
        expect(pane.left).toBeGreaterThanOrEqual(VIEWPORT_MARGIN);
        expect(pane.right).toBeLessThanOrEqual(390 - VIEWPORT_MARGIN);
    });

    it('moves the card with its target when the page scrolls', () => {
        vi.useFakeTimers({ toFake: ['requestAnimationFrame', 'cancelAnimationFrame', 'performance'] });
        resizeViewport(1280, 800);
        layOutCard({ width: 324, height: 150 });
        const { target, moveTo } = appendTarget({ left: 100, top: 300, width: 32, height: 32 });
        startRenderer().show({ ...WELCOME, target, side: 'right' });
        // Past the frames measured while a step settles: only the scroll moves the card now.
        vi.advanceTimersByTime(5000);

        moveTo({ left: 300, top: 300, width: 32, height: 32 });
        document.dispatchEvent(new Event('scroll'));
        vi.advanceTimersToNextFrame();

        // The target now ends at 332: 8px of hole and 12px of gap after it.
        expect(cardPaneBox(324).left).toBe(352);
    });

    it('re-sizes a floating card to the viewport when the window is resized', () => {
        // CDK's ViewportRuler reports a resize through rxjs's auditTime, which schedules with setInterval.
        vi.useFakeTimers({
            toFake: ['requestAnimationFrame', 'cancelAnimationFrame', 'performance', 'setInterval', 'clearInterval'],
        });
        resizeViewport(1280, 500);
        startRenderer().show(WELCOME);
        vi.advanceTimersByTime(5000);

        resizeViewport(1280, 400);
        window.dispatchEvent(new Event('resize'));
        vi.advanceTimersByTime(100);

        expect(card().style.maxHeight).toBe('384px');
    });

    it.each<[description: string, contentHeight: number, isTabStop: boolean]>([
        ['makes the text of a card too tall for its room a Tab stop, so a keyboard can scroll it', 600, true],
        ['leaves the text of a card that fits out of the Tab order', 300, false],
    ])('%s', (_description, contentHeight, isTabStop) => {
        layOutContent(contentHeight, 300);
        startRenderer().show({ ...WELCOME, content: { title: 'Welcome', body: ['A long introduction.'] } });

        const stops = tabStops();

        const title = card().querySelector('h2');
        expect(stops.some((stop) => stop !== card() && stop.contains(title))).toBe(isTabStop);
        // The buttons are Tab stops either way.
        expect(stops.map((stop) => stop.getAttribute('aria-label') ?? stop.textContent?.trim())).toEqual(
            expect.arrayContaining(['Close tour', 'Next'])
        );
    });
});
