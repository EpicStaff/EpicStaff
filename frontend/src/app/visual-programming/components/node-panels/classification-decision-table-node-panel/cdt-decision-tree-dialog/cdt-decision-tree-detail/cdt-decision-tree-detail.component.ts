import { animate, style, transition, trigger } from '@angular/animations';
import { ChangeDetectionStrategy, Component, input, output, signal } from '@angular/core';

import { AppSvgIconComponent } from '../../../../../../shared/components/app-svg-icon/app-svg-icon.component';
import { CopyButtonComponent } from '../../../../../../shared/components/copy-button/copy-button.component';
import { CDT_TREE_COPY } from '../cdt-decision-tree.constants';
import { CdtTreeBlock } from '../cdt-decision-tree.model';
import { CdtDecisionTreeCodeComponent } from '../cdt-decision-tree-code/cdt-decision-tree-code.component';
import { EXPLANATION_STUB_MODEL, EXPLANATION_STUB_TEXT } from './explanation-stub';

/**
 * The read-only detail window for one block of the decision tree.
 *
 * Presentational: takes a block, renders what it already carries, emits when it
 * wants closing.
 *
 * Docked beside the canvas rather than anchored to the block, which is what lets
 * a second click swap its contents instead of tearing the window down — the
 * dialog keeps the selected id and this component just re-renders.
 */
@Component({
    selector: 'app-cdt-decision-tree-detail',
    standalone: true,
    imports: [AppSvgIconComponent, CopyButtonComponent, CdtDecisionTreeCodeComponent],
    templateUrl: './cdt-decision-tree-detail.component.html',
    styleUrls: ['./cdt-decision-tree-detail.component.scss'],
    animations: [
        /**
         * Not the shared `expandCollapseAnimation`: its expanded state caps at
         * `max-height: 1000px`, and both sections here can exceed that.
         *
         * `:enter`/`:leave` rather than named states, because the engine drops the
         * inline styles it applied once the transition ends. A `state()` leaves a
         * measured pixel height behind, which clips when the text rewraps.
         */
        trigger('sectionExpand', [
            transition(':enter', [
                style({ height: '0', opacity: 0 }),
                animate('180ms ease-in-out', style({ height: '*', opacity: 1 })),
            ]),
            transition(':leave', [animate('180ms ease-in-out', style({ height: '0', opacity: 0 }))]),
        ]),
    ],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class CdtDecisionTreeDetailComponent {
    /** Only openable blocks reach this component, so `detail` is always present. */
    public readonly block = input.required<CdtTreeBlock>();

    public readonly closed = output<void>();

    protected readonly copy = CDT_TREE_COPY;

    /** Both start open: the window exists to show them. */
    protected readonly explanationOpen = signal(true);
    protected readonly dataOpen = signal(true);

    // Stubs until the explanation endpoints exist — see `explanation-stub.ts`.
    protected readonly explanationText = EXPLANATION_STUB_TEXT;
    protected readonly explanationModel = EXPLANATION_STUB_MODEL;

    protected toggleExplanation(): void {
        this.explanationOpen.update((open) => !open);
    }

    protected toggleData(): void {
        this.dataOpen.update((open) => !open);
    }
}
