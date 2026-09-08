import { DIALOG_DATA, DialogRef } from '@angular/cdk/dialog';
import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { LabelTreeNode } from '@shared/models';
import { LABELS_STORE } from '@shared/services';

import { AppSvgIconComponent } from '../../app-svg-icon/app-svg-icon.component';
import { ButtonComponent } from '../../buttons/button/button.component';
import { CheckboxComponent } from '../../checkbox/checkbox.component';

export type IncludeExcludeTab = 'primary' | 'labels';

export interface IncludeExcludeEntity {
    id: number;
    name: string;
}

export interface IncludeExcludeTabConfig {
    label: string; // tab caption
    icon: string; // svg-icon name
    searchPlaceholder?: string;
    emptyText?: string;
}

export interface AppIncludeExcludeDialogData {
    /** Dialog header (default 'Include'). */
    title?: string;
    /** Which tab opens first (default 'primary'). */
    initialTab?: IncludeExcludeTab;
    primaryTab: IncludeExcludeTabConfig;
    /** Labels tab is always rendered; the callee supplies label items via LABELS_STORE. */
    labelsTab?: Partial<IncludeExcludeTabConfig>;
    /** Primary-entity items rendered in the primary tab. */
    items: IncludeExcludeEntity[];
    /** Currently-selected primary ids. `null` means "all selected". */
    selectedItemIds: number[] | null;
    /** Currently-selected label ids. `null` means "all selected". */
    selectedLabelIds: number[] | null;
}

export interface AppIncludeExcludeDialogResult {
    includedItemIds: number[] | null;
    includedLabelIds: number[] | null;
}

interface FlatLabelNode {
    node: LabelTreeNode;
    depth: number;
}

/**
 * Generic include/exclude picker with two tabs — a primary entity list (flows,
 * tools, …) supplied via `data.items`, and a labels tree resolved from the
 * `LABELS_STORE` injection token. Callers must ensure that token is provided
 * at `Dialog.open` time (typically via `providers: [{ provide: LABELS_STORE,
 * useExisting: <FeatureLabelsService> }]`).
 */
@Component({
    selector: 'app-include-exclude-dialog',
    imports: [FormsModule, ButtonComponent, AppSvgIconComponent, CheckboxComponent],
    templateUrl: './app-include-exclude-dialog.component.html',
    styleUrls: ['./app-include-exclude-dialog.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class AppIncludeExcludeDialogComponent {
    private readonly dialogRef = inject<DialogRef<AppIncludeExcludeDialogResult | undefined>>(DialogRef);
    private readonly data = inject<AppIncludeExcludeDialogData>(DIALOG_DATA);
    private readonly labelsStorage = inject(LABELS_STORE);

    public readonly title = this.data.title ?? 'Include';
    public readonly primaryTab = this.data.primaryTab;
    public readonly labelsTab: IncludeExcludeTabConfig = {
        label: this.data.labelsTab?.label ?? 'Labels',
        icon: this.data.labelsTab?.icon ?? 'label',
        searchPlaceholder: this.data.labelsTab?.searchPlaceholder ?? 'Search label...',
        emptyText: this.data.labelsTab?.emptyText ?? 'No labels match the search.',
    };

    public readonly activeTab = signal<IncludeExcludeTab>(this.data.initialTab ?? 'primary');
    public readonly primarySearch = signal<string>('');
    public readonly labelSearch = signal<string>('');

    private readonly allItems = this.data.items;
    private readonly allLabels = this.labelsStorage.labels;
    private readonly labelTree = this.labelsStorage.labelTree;

    public readonly selectedItemIds = signal<Set<number>>(
        new Set(this.data.selectedItemIds ?? this.allItems.map((i) => i.id))
    );
    public readonly selectedLabelIds = signal<Set<number>>(
        new Set(this.data.selectedLabelIds ?? this.allLabels().map((l) => l.id))
    );

    public readonly expandedLabelIds = signal<Set<number>>(new Set());

    public readonly filteredItems = computed(() => {
        const term = this.primarySearch().toLowerCase().trim();
        if (!term) return this.allItems;
        return this.allItems.filter((i) => i.name.toLowerCase().includes(term));
    });

    public readonly flatLabelTree = computed<FlatLabelNode[]>(() => {
        const result: FlatLabelNode[] = [];
        const term = this.labelSearch().toLowerCase().trim();
        const expanded = this.expandedLabelIds();

        const matchesTerm = (node: LabelTreeNode): boolean => {
            if (!term) return true;
            if (node.name.toLowerCase().includes(term)) return true;
            return node.children.some(matchesTerm);
        };

        const walk = (nodes: LabelTreeNode[], depth: number) => {
            for (const node of nodes) {
                if (!matchesTerm(node)) continue;
                result.push({ node, depth });
                const shouldExpand = term ? true : expanded.has(node.id);
                if (shouldExpand && node.children.length > 0) {
                    walk(node.children, depth + 1);
                }
            }
        };
        walk(this.labelTree(), 0);
        return result;
    });

    public readonly totalItemCount = computed(() => this.allItems.length);
    public readonly totalLabelCount = computed(() => this.allLabels().length);

    public readonly selectedItemCount = computed(() => this.selectedItemIds().size);
    public readonly selectedLabelCount = computed(() => this.selectedLabelIds().size);

    public setActiveTab(tab: IncludeExcludeTab): void {
        this.activeTab.set(tab);
    }

    public isItemSelected(id: number): boolean {
        return this.selectedItemIds().has(id);
    }

    public toggleItem(id: number): void {
        this.selectedItemIds.update((set) => {
            const next = new Set(set);
            if (next.has(id)) next.delete(id);
            else next.add(id);
            return next;
        });
    }

    public isLabelSelected(id: number): boolean {
        return this.selectedLabelIds().has(id);
    }

    public toggleLabel(id: number): void {
        this.selectedLabelIds.update((set) => {
            const next = new Set(set);
            if (next.has(id)) next.delete(id);
            else next.add(id);
            return next;
        });
    }

    public isExpanded(id: number): boolean {
        return this.expandedLabelIds().has(id);
    }

    public toggleExpand(id: number): void {
        this.expandedLabelIds.update((set) => {
            const next = new Set(set);
            if (next.has(id)) next.delete(id);
            else next.add(id);
            return next;
        });
    }

    public selectAll(): void {
        if (this.activeTab() === 'primary') {
            this.selectedItemIds.set(new Set(this.allItems.map((i) => i.id)));
        } else {
            this.selectedLabelIds.set(new Set(this.allLabels().map((l) => l.id)));
        }
    }

    public cancel(): void {
        this.dialogRef.close(undefined);
    }

    public save(): void {
        const allItemIds = this.allItems.map((i) => i.id);
        const allLabelIds = this.allLabels().map((l) => l.id);
        const itemSelection = this.selectedItemIds();
        const labelSelection = this.selectedLabelIds();

        const includedItemIds =
            itemSelection.size === allItemIds.length && allItemIds.every((id) => itemSelection.has(id))
                ? null
                : Array.from(itemSelection);

        const includedLabelIds =
            labelSelection.size === allLabelIds.length && allLabelIds.every((id) => labelSelection.has(id))
                ? null
                : Array.from(labelSelection);

        this.dialogRef.close({ includedItemIds, includedLabelIds });
    }

    public indentPadding(depth: number): string {
        return `${0.75 + depth * 1.25}rem`;
    }
}
