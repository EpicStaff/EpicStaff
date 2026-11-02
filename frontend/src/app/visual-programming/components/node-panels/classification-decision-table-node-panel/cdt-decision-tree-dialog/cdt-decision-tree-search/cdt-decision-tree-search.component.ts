import {
    ChangeDetectionStrategy,
    Component,
    computed,
    ElementRef,
    input,
    output,
    viewChild,
    viewChildren,
} from '@angular/core';
import { MatTooltip } from '@angular/material/tooltip';
import { TooltipOnOverflowDirective } from '@shared/directives';

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
    imports: [TooltipOnOverflowDirective, MatTooltip, AppSvgIconComponent, ButtonComponent],
    templateUrl: './cdt-decision-tree-search.component.html',
    styleUrls: ['./cdt-decision-tree-search.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
    // Escape here, ahead of the tooltip of the focused entry, which would take the first one on the body.
    host: {
        '(keydown.tab)': 'onTab($event)',
        '(keydown.shift.tab)': 'onTab($event)',
        '(keydown.escape)': 'onEscape($event)',
    },
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
    /** Tab went off an end of the panel; the dialog takes the focus back to the search box. */
    public readonly tabbedOut = output<'backward' | 'forward'>();

    private readonly items = viewChildren<ElementRef<HTMLButtonElement>>('item');
    private readonly clearButton = viewChild.required('clearButton', { read: ButtonComponent });
    private readonly clearButtonHost = viewChild.required('clearButton', { read: ElementRef });
    private readonly saveButtonHost = viewChild.required('saveButton', { read: ElementRef });

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

    /** The first entry, or Clear Filter when nothing matches. */
    public focusFirst(): void {
        const firstItem = this.items()[0];
        if (firstItem) firstItem.nativeElement.focus();
        else this.clearButton().focus();
    }

    protected onEscape(event: Event): void {
        if (event.defaultPrevented) return;
        event.preventDefault();
        event.stopPropagation();
        this.cancelled.emit();
    }

    protected onTab(event: Event): void {
        const keyboardEvent = event as KeyboardEvent;
        const target = keyboardEvent.target as Node;
        const first: HTMLElement = this.items()[0]?.nativeElement ?? this.clearButtonHost().nativeElement;
        const isLeavingBackward = keyboardEvent.shiftKey && first.contains(target);
        const isLeavingForward = !keyboardEvent.shiftKey && this.saveButtonHost().nativeElement.contains(target);
        if (!isLeavingBackward && !isLeavingForward) return;
        keyboardEvent.preventDefault();
        this.tabbedOut.emit(isLeavingBackward ? 'backward' : 'forward');
    }
}
