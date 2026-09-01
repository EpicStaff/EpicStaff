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
                    [class.cdt-shape__outline--region]="shape() === 'region'"
                    x="0"
                    y="0"
                    [attr.width]="width()"
                    [attr.height]="height()"
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
                    y1="0"
                    [attr.x2]="bandOffset()"
                    [attr.y2]="height()"
                />
                <line
                    class="cdt-shape__rule"
                    [attr.x1]="width() - bandOffset()"
                    y1="0"
                    [attr.x2]="width() - bandOffset()"
                    [attr.y2]="height()"
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

            // Fill and stroke are the block's to set: a diamond and a parallelogram
            // cannot carry a CSS background or border, so the states the design
            // specifies reach the silhouette through these two properties.
            // The design's card surface (#2b2d30) for every block. Its token is
            // declared only in the dark palette, so the chain falls back to the
            // dialog's raised alias and then to the app's node surface rather than
            // leaving a light theme with a dark block.
            .cdt-shape__outline {
                fill: var(
                    --cdt-shape-fill,
                    var(--color-flow-card-bg, var(--cdt-tree-raised, var(--color-nodes-background)))
                );
                stroke: var(--cdt-shape-stroke, transparent);
                stroke-width: 1;
            }

            // The region is a boundary, not a block: an outline with nothing
            // behind it, so the canvas and the rules inside stay visible. Drawn in
            // the error colour because it is the boundary the Error edge leaves —
            // anything inside it that throws goes there.
            .cdt-shape__outline--region {
                fill: none;
                stroke: var(--cdt-tree-error, var(--color-error));
                stroke-width: 1;
                stroke-dasharray: 6 5;
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
        () =>
            this.shape() === 'terminator' ||
            this.shape() === 'process' ||
            this.shape() === 'predefined-process' ||
            this.shape() === 'region'
    );

    protected readonly cornerRadius = computed(() => {
        if (this.shape() === 'terminator') return this.height() / 2;
        if (this.shape() === 'region') return 12;
        return Math.min(10, this.height() / 5);
    });

    protected readonly bandOffset = computed(() => Math.min(14, this.width() / 8));

    protected readonly points = computed(() => {
        const w = this.width();
        const h = this.height();
        const s = this.skew();

        switch (this.shape()) {
            case 'decision':
                return `${w / 2},0 ${w},${h / 2} ${w / 2},${h} 0,${h / 2}`;
            case 'data':
                return `${s},0 ${w},0 ${w - s},${h} 0,${h}`;
            default:
                return '';
        }
    });
}
