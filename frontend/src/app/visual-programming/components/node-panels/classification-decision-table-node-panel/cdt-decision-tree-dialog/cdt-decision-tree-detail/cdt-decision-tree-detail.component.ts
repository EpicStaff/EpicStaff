import { animate, style, transition, trigger } from '@angular/animations';
import { ChangeDetectionStrategy, Component, computed, input, output, signal } from '@angular/core';
import { MatTooltipModule } from '@angular/material/tooltip';

import { AppSvgIconComponent } from '../../../../../../shared/components/app-svg-icon/app-svg-icon.component';
import { CopyButtonComponent } from '../../../../../../shared/components/copy-button/copy-button.component';
import { CDT_TREE_COPY } from '../cdt-decision-tree.constants';
import { CdtTreeBlock } from '../cdt-decision-tree.model';
import { CdtDecisionTreeCodeComponent } from '../cdt-decision-tree-code/cdt-decision-tree-code.component';
import { CdtExplanationState } from '../cdt-explain.model';

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
    imports: [AppSvgIconComponent, CopyButtonComponent, MatTooltipModule, CdtDecisionTreeCodeComponent],
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

    /**
     * The explanation of the block being shown, or null when none was asked for.
     *
     * Owned by the dialog: this component's instance outlives a switch between
     * blocks, so anything kept here would survive into the next block's window.
     */
    public readonly explanation = input<CdtExplanationState | null>(null);

    /**
     * Whether this block can be explained at all. False for the one clickable
     * block that has nothing to send — a prompt step whose config went missing.
     */
    public readonly explainAvailable = input<boolean>(true);

    /** Whether the model picker is showing, so the chevron can say so. */
    public readonly explainMenuOpen = input<boolean>(false);

    /**
     * Said here as well as on the canvas marker: this is where the text is read,
     * and a reader who opened the block from the search panel never saw the marker.
     */
    public readonly outdated = input<boolean>(false);

    public readonly closed = output<void>();
    public readonly explainRequested = output<void>();
    /**
     * The chevron element, so the dialog can anchor the picker to it. The button
     * lives here; the options and the overlay do not.
     */
    public readonly explainMenuRequested = output<HTMLElement>();

    protected readonly copy = CDT_TREE_COPY;

    /** Both start open: the window exists to show them. */
    protected readonly explanationOpen = signal(true);
    protected readonly dataOpen = signal(true);

    /** Unpacked into three narrow reads, so the narrowing stays in TypeScript. */
    protected readonly explanationLoading = computed(() => this.explanation()?.status === 'loading');

    protected readonly explanationReady = computed(() => {
        const state = this.explanation();
        return state?.status === 'ready' ? state : null;
    });

    protected readonly explanationError = computed(() => {
        const state = this.explanation();
        return state?.status === 'error' ? state.message : null;
    });

    protected onMenuClick(event: MouseEvent): void {
        this.explainMenuRequested.emit(event.currentTarget as HTMLElement);
    }

    protected toggleExplanation(): void {
        this.explanationOpen.update((open) => !open);
    }

    protected toggleData(): void {
        this.dataOpen.update((open) => !open);
    }
}
