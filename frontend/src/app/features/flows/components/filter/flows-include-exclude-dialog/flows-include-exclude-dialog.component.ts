import { DIALOG_DATA, DialogRef } from '@angular/cdk/dialog';
import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';

import { AppSvgIconComponent } from '../../../../../shared/components/app-svg-icon/app-svg-icon.component';
import { ButtonComponent } from '../../../../../shared/components/buttons/button/button.component';
import { CheckboxComponent } from '../../../../../shared/components/checkbox/checkbox.component';
import { GetGraphLightRequest } from '../../../models/graph.model';
import { LabelsStorageService, LabelTreeNode } from '../../../services/labels-storage.service';

export type IncludeExcludeTab = 'flows' | 'labels';

export interface IncludeExcludeDialogData {
    initialTab?: IncludeExcludeTab;
    flows: GetGraphLightRequest[];
    selectedFlowIds: number[] | null; // null = all selected
    selectedLabelIds: number[] | null;
}

export interface IncludeExcludeDialogResult {
    includedFlowIds: number[] | null;
    includedLabelIds: number[] | null;
}

interface FlatLabelNode {
    node: LabelTreeNode;
    depth: number;
}

@Component({
    selector: 'app-flows-include-exclude-dialog',
    imports: [FormsModule, ButtonComponent, AppSvgIconComponent, CheckboxComponent],
    templateUrl: './flows-include-exclude-dialog.component.html',
    styleUrls: ['./flows-include-exclude-dialog.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class FlowsIncludeExcludeDialogComponent {
    private readonly dialogRef = inject<DialogRef<IncludeExcludeDialogResult | undefined>>(DialogRef);
    private readonly data = inject<IncludeExcludeDialogData>(DIALOG_DATA);
    private readonly labelsStorage = inject(LabelsStorageService);

    public readonly activeTab = signal<IncludeExcludeTab>(this.data.initialTab ?? 'flows');
    public readonly flowSearch = signal<string>('');
    public readonly labelSearch = signal<string>('');

    private readonly allFlows = this.data.flows;
    private readonly allLabels = this.labelsStorage.labels;
    private readonly labelTree = this.labelsStorage.labelTree;

    public readonly selectedFlowIds = signal<Set<number>>(
        new Set(this.data.selectedFlowIds ?? this.allFlows.map((f) => f.id))
    );
    public readonly selectedLabelIds = signal<Set<number>>(
        new Set(this.data.selectedLabelIds ?? this.allLabels().map((l) => l.id))
    );

    public readonly expandedLabelIds = signal<Set<number>>(new Set());

    public readonly filteredFlows = computed(() => {
        const term = this.flowSearch().toLowerCase().trim();
        if (!term) return this.allFlows;
        return this.allFlows.filter((f) => f.name.toLowerCase().includes(term));
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

    public readonly totalFlowCount = computed(() => this.allFlows.length);
    public readonly totalLabelCount = computed(() => this.allLabels().length);

    public readonly selectedFlowCount = computed(() => this.selectedFlowIds().size);
    public readonly selectedLabelCount = computed(() => this.selectedLabelIds().size);

    public setActiveTab(tab: IncludeExcludeTab): void {
        this.activeTab.set(tab);
    }

    public isFlowSelected(id: number): boolean {
        return this.selectedFlowIds().has(id);
    }

    public toggleFlow(id: number): void {
        this.selectedFlowIds.update((set) => {
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
        if (this.activeTab() === 'flows') {
            this.selectedFlowIds.set(new Set(this.allFlows.map((f) => f.id)));
        } else {
            this.selectedLabelIds.set(new Set(this.allLabels().map((l) => l.id)));
        }
    }

    public cancel(): void {
        this.dialogRef.close(undefined);
    }

    public save(): void {
        const allFlowIds = this.allFlows.map((f) => f.id);
        const allLabelIds = this.allLabels().map((l) => l.id);
        const flowSelection = this.selectedFlowIds();
        const labelSelection = this.selectedLabelIds();

        const includedFlowIds =
            flowSelection.size === allFlowIds.length && allFlowIds.every((id) => flowSelection.has(id))
                ? null
                : Array.from(flowSelection);

        const includedLabelIds =
            labelSelection.size === allLabelIds.length && allLabelIds.every((id) => labelSelection.has(id))
                ? null
                : Array.from(labelSelection);

        this.dialogRef.close({ includedFlowIds, includedLabelIds });
    }

    public indentPadding(depth: number): string {
        return `${0.75 + depth * 1.25}rem`;
    }
}
