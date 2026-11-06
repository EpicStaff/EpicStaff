import { ConnectedPosition } from '@angular/cdk/overlay';
import { Component, input } from '@angular/core';

import { DisplaySegment } from '../../utils/diff';

// Trial: the label above the value in the tooltip. Drop it here, in the template and in the styles to remove it.
/** The label above the value in the tooltip; a mark's description says the same. */
export const CURRENT_VALUE_LABEL = 'Current canvas';

/**
 * What a screen reader hears for a changed value, the words of its tooltip: "Current canvas: x > 1". Built from the
 * shown segments, so it is cut like the tooltip: a screen reader is not read a whole long value.
 */
export function currentValueDescription(segments: readonly DisplaySegment[]): string {
    return `${CURRENT_VALUE_LABEL}: ${segments.map((segment) => segment.text).join('')}`;
}

/**
 * Put on an element inside a marked field, row or grid cell that shows a tooltip of its own (a help icon, the Route
 * Code status icon, the Prompt ID "Open in Prompt Library" button): while the pointer or the focus is on it, the diff
 * tooltip stays closed, so two tooltips never show at once. The rest of the marked element shows the diff tooltip.
 */
export const OWN_TOOLTIP_ATTRIBUTE = 'data-own-tooltip';

/** Whether `target` is (in) an element inside `container` that shows a tooltip of its own (`OWN_TOOLTIP_ATTRIBUTE`). */
export function isOnOwnTooltip(target: EventTarget | null, container: Element | null): boolean {
    const ownTooltip = target instanceof Element ? target.closest(`[${OWN_TOOLTIP_ATTRIBUTE}]`) : null;
    return ownTooltip !== null && container !== null && container.contains(ownTooltip);
}

/** The side of its element a diff tooltip opened on (`DIFF_MARK_TOOLTIP_POSITIONS`). */
export type DiffTooltipSide = 'above' | 'below';

/**
 * Where an element inside a marked row places its own tooltip (`matTooltipPosition`) so it never covers the row's diff
 * tooltip: on the other side of the row.
 */
export function sideAwayFrom(diffTooltipSide: DiffTooltipSide): DiffTooltipSide {
    return diffTooltipSide === 'above' ? 'below' : 'above';
}

/** Above the marked element, centred; below it when there is no room above. */
export const DIFF_MARK_TOOLTIP_POSITIONS: ConnectedPosition[] = [
    { originX: 'center', originY: 'top', overlayX: 'center', overlayY: 'bottom', offsetY: -8 },
    { originX: 'center', originY: 'bottom', overlayX: 'center', overlayY: 'top', offsetY: 8 },
];

/**
 * The tooltip of a version diff mark, shown in a CDK overlay above the marked field or row: the current canvas value,
 * the parts a restore replaces struck through, or a fixed hint instead; above it, the full text of a cut-off cell the
 * tooltip is over; below it, sentences for changes that have no value to show. Visual only: the mark gives screen
 * readers the same words another way, so the tooltip is hidden from them. Every value is shown as text.
 */
@Component({
    selector: 'app-diff-mark-tooltip',
    template: `
        <div
            class="diff-field-mark__tooltip"
            aria-hidden="true"
        >
            @if (heading(); as shownHeading) {
                <span class="diff-field-mark__tooltip-heading">{{ shownHeading }}</span>
            }
            @if (hint(); as shownHint) {
                <span class="diff-field-mark__tooltip-hint">{{ shownHint }}</span>
            } @else if (segments(); as shownSegments) {
                <span class="diff-field-mark__tooltip-label">{{ currentValueLabel }}</span>
                <span class="diff-field-mark__tooltip-value">
                    @for (segment of shownSegments; track $index) {
                        <span [class.diff-field-mark__struck]="segment.struck">{{ segment.text }}</span>
                    }
                </span>
            }
            <!-- No style of its own: the tooltip's flex column stacks the lines; the class names them for tests. -->
            @for (line of lines(); track $index) {
                <span class="diff-field-mark__tooltip-line">{{ line }}</span>
            }
        </div>
    `,
    styleUrls: ['./diff-mark-tooltip.component.scss'],
})
export class DiffMarkTooltipComponent {
    /**
     * Above everything else when set: the full text of the version's cell the tooltip is over when the cell cuts it
     * off. The cell's own tooltip would show it; on a marked row this tooltip shows instead.
     */
    readonly heading = input<string | null>(null);
    /** Shown instead of the value when set. */
    readonly hint = input<string | null>(null);
    /** The current canvas value; `null` when no value is shown, only `lines`. */
    readonly segments = input<readonly DisplaySegment[] | null>([]);
    /** Sentences below the value, one per line: changes with no value to show ("Restore adds a linked region"). */
    readonly lines = input<readonly string[]>([]);

    protected readonly currentValueLabel = CURRENT_VALUE_LABEL;
}
