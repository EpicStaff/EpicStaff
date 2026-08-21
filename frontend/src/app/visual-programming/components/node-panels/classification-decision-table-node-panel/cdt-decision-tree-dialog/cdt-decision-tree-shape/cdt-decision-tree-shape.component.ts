import { ChangeDetectionStrategy, Component, computed, input } from '@angular/core';

import { CdtTreeShape } from '../cdt-decision-tree.model';

/**
 * The outline of one flowchart shape, drawn as SVG.
 *
 * SVG rather than `clip-path` because every shape in the mockup is outlined and a
 * clip path cannot carry a stroke. The viewBox matches the real pixel size, so
 * nothing is distorted and the same component can draw both a full-size canvas
 * block and a legend glyph — which is what keeps the legend honest.
 */
@Component({
    selector: 'app-cdt-decision-tree-shape',
    standalone: true,
    template: `
        <svg
            class="cdt-shape"
            [attr.viewBox]="viewBox()"
            [attr.width]="width()"
            [attr.height]="height()"
            aria-hidden="true"
        >
            @if (isRounded()) {
                <rect
                    class="cdt-shape__outline"
                    x="1"
                    y="1"
                    [attr.width]="width() - 2"
                    [attr.height]="height() - 2"
                    [attr.rx]="cornerRadius()"
                />
            } @else {
                <polygon
                    class="cdt-shape__outline"
                    [attr.points]="points()"
                />
            }

            @if (shape() === 'predefined-process') {
                <line
                    class="cdt-shape__rule"
                    [attr.x1]="bandOffset()"
                    y1="1"
                    [attr.x2]="bandOffset()"
                    [attr.y2]="height() - 1"
                />
                <line
                    class="cdt-shape__rule"
                    [attr.x1]="width() - bandOffset()"
                    y1="1"
                    [attr.x2]="width() - bandOffset()"
                    [attr.y2]="height() - 1"
                />
            }
        </svg>
    `,
    styles: [
        `
            :host {
                display: block;
                position: absolute;
                inset: 0;
                pointer-events: none;
            }

            .cdt-shape {
                display: block;
                width: 100%;
                height: 100%;
                overflow: visible;
            }

            .cdt-shape__outline {
                fill: var(--cdt-tree-raised, #2b2d30);
                stroke: var(--color-divider-regular);
                stroke-width: 1;
            }

            .cdt-shape__rule {
                stroke: var(--color-divider-regular);
                stroke-width: 1;
            }
        `,
    ],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class CdtDecisionTreeShapeComponent {
    public readonly shape = input.required<CdtTreeShape>();
    public readonly width = input<number>(268);
    public readonly height = input<number>(76);

    /** Horizontal inset of the slanted or pointed edges. */
    private readonly skew = computed(() => Math.min(18, this.width() / 6));

    protected readonly viewBox = computed(() => `0 0 ${this.width()} ${this.height()}`);

    protected readonly isRounded = computed(
        () => this.shape() === 'terminator' || this.shape() === 'process' || this.shape() === 'predefined-process'
    );

    protected readonly cornerRadius = computed(() =>
        this.shape() === 'terminator' ? (this.height() - 2) / 2 : Math.min(10, this.height() / 5)
    );

    protected readonly bandOffset = computed(() => Math.min(14, this.width() / 8));

    protected readonly points = computed(() => {
        const w = this.width();
        const h = this.height();
        const s = this.skew();

        switch (this.shape()) {
            case 'decision':
                return `${w / 2},1 ${w - 1},${h / 2} ${w / 2},${h - 1} 1,${h / 2}`;
            case 'data':
                return `${s},1 ${w - 1},1 ${w - s},${h - 1} 1,${h - 1}`;
            default:
                return '';
        }
    });
}
