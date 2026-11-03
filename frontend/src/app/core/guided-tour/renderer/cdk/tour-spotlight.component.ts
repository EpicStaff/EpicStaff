import { Component, computed, input } from '@angular/core';

import { TourRect, TourViewportSize } from './tour-target-geometry';

const HOLE_PADDING = 8;
const HOLE_RADIUS = 8;
const CDK_OVERLAY_PANE_SELECTOR = '.cdk-overlay-pane';

/**
 * Space between a target and the edge of its hole. None for a target inside a CDK overlay pane: around a dropdown the
 * padding would lie over the dropdown's transparent backdrop, and a click there would close the dropdown.
 */
export function tourHolePadding(target: Element): number {
    return target.closest(CDK_OVERLAY_PANE_SELECTOR) ? 0 : HOLE_PADDING;
}

/**
 * Dims the viewport except a rounded hole around the target. The dimmed area takes clicks (and drops them); the hole
 * takes none, so they reach the target under it.
 */
@Component({
    selector: 'app-tour-spotlight',
    template: `
        <svg
            class="tour-spotlight"
            aria-hidden="true"
            [attr.width]="viewport().width"
            [attr.height]="viewport().height"
        >
            <path
                class="tour-spotlight__dim"
                fill-rule="evenodd"
                [attr.d]="path()"
            />
        </svg>
    `,
    styleUrl: './tour-spotlight.component.scss',
})
export class TourSpotlightComponent {
    /** The highlighted element; null for no hole. */
    readonly target = input<Element | null>(null);
    /** The target's box in viewport coordinates; null for no hole. */
    readonly targetRect = input<TourRect | null>(null);
    readonly viewport = input.required<TourViewportSize>();

    /** The viewport, then the hole: with the even-odd rule the second shape cuts the first. */
    protected readonly path = computed<string>(() => {
        const { width, height } = this.viewport();
        const viewportPath = `M0 0H${width}V${height}H0Z`;
        const target = this.target();
        const rect = this.targetRect();
        if (!target || !rect) {
            return viewportPath;
        }
        const padding = tourHolePadding(target);
        return `${viewportPath}${roundedRectPath(
            rect.left - padding,
            rect.top - padding,
            rect.width + padding * 2,
            rect.height + padding * 2
        )}`;
    });
}

function roundedRectPath(left: number, top: number, width: number, height: number): string {
    const radius = Math.min(HOLE_RADIUS, width / 2, height / 2);
    const right = left + width;
    const bottom = top + height;
    const arc = `A${radius} ${radius} 0 0 1`;
    return [
        `M${left + radius} ${top}`,
        `H${right - radius}`,
        `${arc} ${right} ${top + radius}`,
        `V${bottom - radius}`,
        `${arc} ${right - radius} ${bottom}`,
        `H${left + radius}`,
        `${arc} ${left} ${bottom - radius}`,
        `V${top + radius}`,
        `${arc} ${left + radius} ${top}`,
        'Z',
    ].join('');
}
