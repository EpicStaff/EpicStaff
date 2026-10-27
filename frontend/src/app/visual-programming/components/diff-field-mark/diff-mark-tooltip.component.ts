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

/** Above the marked element, centred; below it when there is no room above. */
export const DIFF_MARK_TOOLTIP_POSITIONS: ConnectedPosition[] = [
    { originX: 'center', originY: 'top', overlayX: 'center', overlayY: 'bottom', offsetY: -8 },
    { originX: 'center', originY: 'bottom', overlayX: 'center', overlayY: 'top', offsetY: 8 },
];

/**
 * The tooltip of a version diff mark, shown in a CDK overlay above the marked field or row: the current canvas value,
 * the parts a restore replaces struck through, or a fixed hint instead. Visual only: the mark gives screen readers the
 * same words another way, so the tooltip is hidden from them. Every value is shown as text.
 */
@Component({
    selector: 'app-diff-mark-tooltip',
    template: `
        <div
            class="diff-field-mark__tooltip"
            aria-hidden="true"
        >
            @if (hint(); as shownHint) {
                <span class="diff-field-mark__tooltip-hint">{{ shownHint }}</span>
            } @else {
                <span class="diff-field-mark__tooltip-label">{{ currentValueLabel }}</span>
                <span class="diff-field-mark__tooltip-value">
                    @for (segment of segments(); track $index) {
                        <span [class.diff-field-mark__struck]="segment.struck">{{ segment.text }}</span>
                    }
                </span>
            }
        </div>
    `,
    styleUrls: ['./diff-mark-tooltip.component.scss'],
})
export class DiffMarkTooltipComponent {
    /** Shown instead of the value when set. */
    readonly hint = input<string | null>(null);
    /** The current canvas value. */
    readonly segments = input<readonly DisplaySegment[]>([]);

    protected readonly currentValueLabel = CURRENT_VALUE_LABEL;
}
