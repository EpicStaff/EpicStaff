import { ChangeDetectionStrategy, Component, computed, input, output } from '@angular/core';
import { MatTooltipModule } from '@angular/material/tooltip';
import { FFlowModule } from '@foblex/flow';

import { AppSvgIconComponent } from '../../../../../../shared/components/app-svg-icon/app-svg-icon.component';
import {
    CDT_TREE_COPY,
    CDT_TREE_SUBTITLE_CODE_LINES,
    CdtTreeIcon,
    ICON_BY_SHAPE,
} from '../cdt-decision-tree.constants';
import { CdtTreePositionedBlock } from '../cdt-decision-tree.model';
import { CdtDecisionTreeShapeComponent } from '../cdt-decision-tree-shape/cdt-decision-tree-shape.component';

/**
 * One block of the decision tree.
 *
 * Connectors come from the layout, one per incident edge, and are positioned by
 * that edge's side. Foblex connectors are single-use: when two edges share one,
 * it drops the colliding edge *and every edge declared after it*, rendering no
 * path and logging nothing. Per-edge connectors make that impossible.
 *
 * `fOutputDisabled` / `fInputDisabled` keep them non-interactive, so the
 * diagram stays read-only.
 */
@Component({
    selector: 'app-cdt-decision-tree-block',
    standalone: true,
    // The connector directives are not standalone in @foblex/flow 18.4.0, so they
    // have to come in through the module rather than being imported directly.
    imports: [FFlowModule, MatTooltipModule, AppSvgIconComponent, CdtDecisionTreeShapeComponent],
    templateUrl: './cdt-decision-tree-block.component.html',
    styleUrls: ['./cdt-decision-tree-block.component.scss'],
    host: {
        '[class.cdt-tree-block--dimmed]': 'dimmed()',
        '[class.cdt-tree-block--match]': 'matched()',
        '[class.cdt-tree-block--selected]': 'selected()',
        '[class.cdt-tree-block--clickable]': 'block().clickable',
        // The text column is sized per silhouette, not per box: a diamond and a
        // parallelogram are narrower than the rectangle they are drawn inside, so
        // centred text that fits the box can still sit outside the shape.
        '[attr.data-shape]': 'block().shape',
        // The rules outline is decoration plus an anchor for the Error edge. Its host
        // is a full-size .f-node, and Foblex gives every node `pointer-events: all` at
        // the same z-index, so whichever comes last in the DOM wins the hit test — the
        // outline, swallowing every click and hover over the rules it surrounds.
        '[class.cdt-tree-block--region]': "block().shape === 'region'",
        // The clamp count has to agree with the height the layout reserved for it,
        // so CSS reads it from the one constant both sides already share.
        '[style.--cdt-tree-subtitle-lines]': 'subtitleLines',
    },
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class CdtDecisionTreeBlockComponent {
    public readonly block = input.required<CdtTreePositionedBlock>();
    public readonly dimmed = input<boolean>(false);
    public readonly matched = input<boolean>(false);

    /** The block whose detail window is open, drawn with the accent border. */
    public readonly selected = input<boolean>(false);

    /**
     * Whether this step's explanation was written for an older version of it. An
     * input rather than a `CdtTreeBlock` field, like `dimmed` and `matched`: the
     * builder is pure and knows nothing about explanations.
     */
    public readonly outdated = input<boolean>(false);

    /** Undefined for the region outline, which is not a step and carries no glyph. */
    protected readonly icon = computed<CdtTreeIcon | undefined>(() => ICON_BY_SHAPE[this.block().shape]);
    protected readonly subtitleLines = CDT_TREE_SUBTITLE_CODE_LINES;
    protected readonly copy = CDT_TREE_COPY;

    /**
     * Asks for this block's detail window.
     *
     * Carries nothing: the window is docked beside the canvas, so it needs no
     * anchor element, and the dialog already knows which block this is from the
     * `@for` it was rendered in.
     */
    public readonly detailRequested = output<void>();

    protected onActivate(): void {
        if (this.block().clickable) {
            this.detailRequested.emit();
        }
    }
}
