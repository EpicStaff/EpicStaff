import { Component, signal } from '@angular/core';
import { TestBed } from '@angular/core/testing';

import { HideOverflowingChildrenDirective } from './hide-overflowing-children.directive';

const CHILD_WIDTH = 40;
const GAP = 10;

// jsdom has no ResizeObserver; the stub keeps the callback so a test can report a resize.
let reportResize: () => void = () => {};
class ResizeObserverStub {
    constructor(callback: () => void) {
        reportResize = callback;
    }
    observe(): void {}
    unobserve(): void {}
    disconnect(): void {}
}

@Component({
    imports: [HideOverflowingChildrenDirective],
    template: `
        <div appHideOverflowingChildren>
            @if (showLateChild()) {
                <button data-hide-on-overflow>late</button>
            }
            <button data-hide-on-overflow>first</button>
            <button data-hide-on-overflow>second</button>
            <button data-hide-on-overflow>third</button>
            <button>pinned</button>
        </div>
    `,
})
class HostComponent {
    readonly showLateChild = signal(false);
}

/**
 * jsdom lays nothing out, so this stands in for the browser: the host spans `hostWidth` from x = 0
 * and lays its shown children out flush right, CHILD_WIDTH each with GAP between them. It is set on
 * the prototype so that children added later are laid out too.
 */
function layOutFlushRight(host: HTMLElement, getHostWidth: () => number): void {
    const isShown = (element: Element): boolean => (element as HTMLElement).style.display !== 'none';
    const rectOf = (element: Element): DOMRect | null => {
        if (element === host) {
            return new DOMRect(0, 0, getHostWidth(), CHILD_WIDTH);
        }
        if (element.parentElement !== host || !isShown(element)) {
            return null;
        }
        const shownChildren = Array.from(host.children).filter(isShown);
        const indexFromRight = shownChildren.length - 1 - shownChildren.indexOf(element);
        const right = getHostWidth() - indexFromRight * (CHILD_WIDTH + GAP);
        return new DOMRect(right - CHILD_WIDTH, 0, CHILD_WIDTH, CHILD_WIDTH);
    };

    vi.spyOn(Element.prototype, 'getBoundingClientRect').mockImplementation(function (this: Element) {
        return rectOf(this) ?? new DOMRect();
    });
    vi.spyOn(Element.prototype, 'getClientRects').mockImplementation(function (this: Element) {
        const rect = rectOf(this);
        return (rect ? [rect] : []) as unknown as DOMRectList;
    });
}

function setUp(initialHostWidth: number) {
    let hostWidth = initialHostWidth;
    const fixture = TestBed.createComponent(HostComponent);
    const host = (fixture.nativeElement as HTMLElement).querySelector<HTMLElement>('[appHideOverflowingChildren]')!;
    layOutFlushRight(host, () => hostWidth);
    fixture.detectChanges();
    runAnimationFrames();

    const shownLabels = (): string[] =>
        (Array.from(host.children) as HTMLElement[])
            .filter((child) => child.style.display !== 'none')
            .map((child) => child.textContent!.trim());
    const resizeHost = (width: number): void => {
        hostWidth = width;
        reportResize();
        runAnimationFrames();
    };
    const addLateChild = async (): Promise<void> => {
        fixture.componentInstance.showLateChild.set(true);
        fixture.detectChanges();
        // MutationObserver reports in a microtask, before the frame it schedules.
        await Promise.resolve();
        runAnimationFrames();
    };
    return { shownLabels, resizeHost, addLateChild };
}

// Frames are queued and run on demand: a real animation frame never runs inside the call that requests it.
let pendingFrames: FrameRequestCallback[] = [];
function runAnimationFrames(): void {
    const frames = pendingFrames;
    pendingFrames = [];
    frames.forEach((frame) => frame(0));
}

describe('HideOverflowingChildrenDirective', () => {
    beforeEach(() => {
        pendingFrames = [];
        vi.stubGlobal('ResizeObserver', ResizeObserverStub);
        vi.stubGlobal('requestAnimationFrame', (callback: FrameRequestCallback) => pendingFrames.push(callback));
    });
    afterEach(() => {
        vi.unstubAllGlobals();
        vi.restoreAllMocks();
    });

    // Four children need 4 × 40 + 3 × 10 = 190px; each hidden one frees 50px. A 1px overflow is
    // tolerated as subpixel rounding, so the narrower side of each limit is 2px short.
    it.each([
        { hostWidth: 190, expected: ['first', 'second', 'third', 'pinned'] },
        { hostWidth: 188, expected: ['second', 'third', 'pinned'] },
        { hostWidth: 140, expected: ['second', 'third', 'pinned'] },
        { hostWidth: 138, expected: ['third', 'pinned'] },
        { hostWidth: 88, expected: ['pinned'] },
        { hostWidth: 20, expected: ['pinned'] },
    ])('at $hostWidth px shows $expected', ({ hostWidth, expected }) => {
        const { shownLabels } = setUp(hostWidth);

        expect(shownLabels()).toEqual(expected);
    });

    it('brings hidden children back once the host is wide enough again', () => {
        const { shownLabels, resizeHost } = setUp(88);

        resizeHost(140);
        expect(shownLabels()).toEqual(['second', 'third', 'pinned']);

        resizeHost(190);
        expect(shownLabels()).toEqual(['first', 'second', 'third', 'pinned']);
    });

    it('hides a child added later when it no longer fits', async () => {
        const { shownLabels, addLateChild } = setUp(190);

        await addLateChild();

        expect(shownLabels()).toEqual(['first', 'second', 'third', 'pinned']);
    });
});
