import { DIALOG_DATA, DialogRef } from '@angular/cdk/dialog';
import { CommonModule } from '@angular/common';
import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { AppSvgIconComponent, CheckboxComponent } from '@shared/components';
import { ButtonComponent } from '@shared/components';
import { LabelTreeNode } from '@shared/models';

import { ToolsLabelsStorageService } from '../../../services/tools-labels-storage.service';

export type IncludeExcludeTab = 'tools' | 'labels';

/**
 * Tool identity as seen by the include/exclude dialog. Both custom and MCP
 * tools reduce to this shape so the dialog stays tool-kind agnostic.
 */
export interface IncludeExcludeToolItem {
    id: number;
    name: string;
}

export interface ToolsIncludeExcludeDialogData {
    initialTab?: IncludeExcludeTab;
    tools: IncludeExcludeToolItem[];
    selectedToolIds: number[] | null; // null = all selected
    selectedLabelIds: number[] | null;
}

export interface ToolsIncludeExcludeDialogResult {
    includedToolIds: number[] | null;
    includedLabelIds: number[] | null;
}

interface FlatLabelNode {
    node: LabelTreeNode;
    depth: number;
}

/**
 * Tools include/exclude picker. Structurally mirrors
 * `FlowsIncludeExcludeDialogComponent` — kept feature-local for now; the plan
 * is to lift a shared version once the flows / tools filter primitives
 * converge.
 */
@Component({
    selector: 'app-tools-include-exclude-dialog',
    standalone: true,
    imports: [CommonModule, FormsModule, ButtonComponent, AppSvgIconComponent, CheckboxComponent],
    templateUrl: './tools-include-exclude-dialog.component.html',
    styleUrls: ['./tools-include-exclude-dialog.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class ToolsIncludeExcludeDialogComponent {
    private readonly dialogRef = inject<DialogRef<ToolsIncludeExcludeDialogResult | undefined>>(DialogRef);
    private readonly data = inject<ToolsIncludeExcludeDialogData>(DIALOG_DATA);
    private readonly labelsStorage = inject(ToolsLabelsStorageService);

    public readonly activeTab = signal<IncludeExcludeTab>(this.data.initialTab ?? 'tools');
    public readonly toolSearch = signal<string>('');
    public readonly labelSearch = signal<string>('');

    private readonly allTools = this.data.tools;
    private readonly allLabels = this.labelsStorage.labels;
    private readonly labelTree = this.labelsStorage.labelTree;

    public readonly selectedToolIds = signal<Set<number>>(
        new Set(this.data.selectedToolIds ?? this.allTools.map((t) => t.id))
    );
    public readonly selectedLabelIds = signal<Set<number>>(
        new Set(this.data.selectedLabelIds ?? this.allLabels().map((l) => l.id))
    );

    public readonly expandedLabelIds = signal<Set<number>>(new Set());

    public readonly filteredTools = computed(() => {
        const term = this.toolSearch().toLowerCase().trim();
        if (!term) return this.allTools;
        return this.allTools.filter((t) => t.name.toLowerCase().includes(term));
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

    public readonly totalToolCount = computed(() => this.allTools.length);
    public readonly totalLabelCount = computed(() => this.allLabels().length);

    public readonly selectedToolCount = computed(() => this.selectedToolIds().size);
    public readonly selectedLabelCount = computed(() => this.selectedLabelIds().size);

    public setActiveTab(tab: IncludeExcludeTab): void {
        this.activeTab.set(tab);
    }

    public isToolSelected(id: number): boolean {
        return this.selectedToolIds().has(id);
    }

    public toggleTool(id: number): void {
        this.selectedToolIds.update((set) => {
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
        if (this.activeTab() === 'tools') {
            this.selectedToolIds.set(new Set(this.allTools.map((t) => t.id)));
        } else {
            this.selectedLabelIds.set(new Set(this.allLabels().map((l) => l.id)));
        }
    }

    public cancel(): void {
        this.dialogRef.close(undefined);
    }

    public save(): void {
        const allToolIds = this.allTools.map((t) => t.id);
        const allLabelIds = this.allLabels().map((l) => l.id);
        const toolSelection = this.selectedToolIds();
        const labelSelection = this.selectedLabelIds();

        const includedToolIds =
            toolSelection.size === allToolIds.length && allToolIds.every((id) => toolSelection.has(id))
                ? null
                : Array.from(toolSelection);

        const includedLabelIds =
            labelSelection.size === allLabelIds.length && allLabelIds.every((id) => labelSelection.has(id))
                ? null
                : Array.from(labelSelection);

        this.dialogRef.close({ includedToolIds, includedLabelIds });
    }

    public indentPadding(depth: number): string {
        return `${0.75 + depth * 1.25}rem`;
    }
}
