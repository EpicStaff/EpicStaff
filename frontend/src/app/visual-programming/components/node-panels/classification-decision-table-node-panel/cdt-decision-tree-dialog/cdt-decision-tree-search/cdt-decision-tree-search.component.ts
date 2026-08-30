import { ChangeDetectionStrategy, Component, computed, input, output } from '@angular/core';

import { AppSvgIconComponent } from '../../../../../../shared/components/app-svg-icon/app-svg-icon.component';
import { ButtonComponent } from '../../../../../../shared/components/buttons/button/button.component';
import { filterByQuery } from '../../cdt-search-filter.util';
import { ICON_BY_SHAPE } from '../cdt-decision-tree.constants';
import { CdtTreeGroup, CdtTreePositionedBlock } from '../cdt-decision-tree.model';

/** One heading of the panel, with the entries that survived the search. */
interface CdtTreeSearchGroup {
    readonly label: string;
    readonly blocks: readonly CdtTreePositionedBlock[];
}

/**
 * The search panel: the tree's blocks as a grouped, clickable list.
 *
 * Stateless on purpose — the dialog owns the text, the overlay, the anchor and
 * everything that moves the canvas — so the list can be exercised on its own.
 */
@Component({
    selector: 'app-cdt-decision-tree-search',
    standalone: true,
    imports: [AppSvgIconComponent, ButtonComponent],
    templateUrl: './cdt-decision-tree-search.component.html',
    styleUrls: ['./cdt-decision-tree-search.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class CdtDecisionTreeSearchComponent {
    /** Reading order, exactly as the builder grouped it: Entry, the rules, Exit. */
    public readonly groups = input.required<readonly CdtTreeGroup[]>();

    /** Every drawn block, so a group's ids can be resolved to what to render. */
    public readonly blocks = input.required<readonly CdtTreePositionedBlock[]>();

    /** What is typed. Read-only here; the dialog holds it. */
    public readonly query = input<string>('');

    public readonly picked = output<string>();
    public readonly applied = output<void>();
    public readonly cancelled = output<void>();
    public readonly cleared = output<void>();

    /** The same icons the canvas blocks carry, so an entry looks like its block. */
    protected readonly iconByShape = ICON_BY_SHAPE;

    /** Groups narrowed by the query, emptied ones dropped so no heading stands alone. */
    protected readonly visibleGroups = computed<CdtTreeSearchGroup[]>(() => {
        const byId = new Map(this.blocks().map((block) => [block.id, block]));
        const query = this.query().trim();

        return this.groups()
            .map((group) => ({
                label: group.label,
                blocks: filterByQuery(
                    group.blockIds
                        .map((id) => byId.get(id))
                        .filter((block): block is CdtTreePositionedBlock => !!block),
                    query,
                    (block) => block.searchText
                ),
            }))
            .filter((group) => group.blocks.length > 0);
    });
}
