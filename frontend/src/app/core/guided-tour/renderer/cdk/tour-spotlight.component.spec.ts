import { TestBed } from '@angular/core/testing';

import { TourSpotlightComponent } from './tour-spotlight.component';
import { TourRect } from './tour-target-geometry';

interface Bounds {
    readonly left: number;
    readonly top: number;
    readonly right: number;
    readonly bottom: number;
}

const VIEWPORT = { width: 1000, height: 800 };
const TARGET_RECT: TourRect = { top: 100, left: 200, width: 120, height: 40 };

function renderSpotlight(target: Element | null, targetRect: TourRect | null): SVGPathElement {
    const fixture = TestBed.createComponent(TourSpotlightComponent);
    fixture.componentRef.setInput('target', target);
    fixture.componentRef.setInput('targetRect', targetRect);
    fixture.componentRef.setInput('viewport', VIEWPORT);
    fixture.detectChanges();
    const path = (fixture.nativeElement as HTMLElement).querySelector('path');
    if (!path) {
        throw new Error('No spotlight path');
    }
    return path;
}

/**
 * The box of each closed shape in an SVG path made of absolute M, H, V and A commands, so the specs check where the
 * dimmed area and its hole are rather than how the path is spelled.
 */
function shapeBounds(path: SVGPathElement): Bounds[] {
    return (path.getAttribute('d') ?? '')
        .split('Z')
        .filter((shape) => shape.trim())
        .map((shape) => {
            const xs: number[] = [];
            const ys: number[] = [];
            for (const [, command, rawArguments] of shape.matchAll(/([MHVA])([^MHVA]*)/g)) {
                const values = rawArguments
                    .trim()
                    .split(/[\s,]+/)
                    .map(Number);
                if (command === 'M') {
                    xs.push(values[0]);
                    ys.push(values[1]);
                } else if (command === 'H') {
                    xs.push(values[0]);
                } else if (command === 'V') {
                    ys.push(values[0]);
                } else {
                    xs.push(values[5]);
                    ys.push(values[6]);
                }
            }
            return { left: Math.min(...xs), top: Math.min(...ys), right: Math.max(...xs), bottom: Math.max(...ys) };
        });
}

function createTarget(container?: HTMLElement): HTMLElement {
    const target = document.createElement('button');
    container?.appendChild(target);
    return target;
}

describe('TourSpotlightComponent', () => {
    it('dims the whole viewport with no hole when there is no target', () => {
        const path = renderSpotlight(null, null);

        expect(shapeBounds(path)).toEqual([{ left: 0, top: 0, right: 1000, bottom: 800 }]);
    });

    it('cuts a hole around a target on the page, with room around it, that clicks pass through', () => {
        const path = renderSpotlight(createTarget(), TARGET_RECT);

        expect(shapeBounds(path)).toEqual([
            { left: 0, top: 0, right: 1000, bottom: 800 },
            { left: 192, top: 92, right: 328, bottom: 148 },
        ]);
        // Even-odd: the hole is not filled, so it is not hit-tested and clicks reach the target.
        expect(path.getAttribute('fill-rule')).toBe('evenodd');
    });

    it('fits the hole exactly to a target inside a CDK overlay pane, so no click lands on the overlay backdrop', () => {
        const pane = document.createElement('div');
        pane.className = 'cdk-overlay-pane';

        const path = renderSpotlight(createTarget(pane), TARGET_RECT);

        expect(shapeBounds(path)[1]).toEqual({ left: 200, top: 100, right: 320, bottom: 140 });
    });
});
