import { animate, state, style, transition, trigger } from '@angular/animations';
import { DIALOG_DATA, DialogRef } from '@angular/cdk/dialog';
import { CommonModule } from '@angular/common';
import { ChangeDetectionStrategy, Component, inject, signal } from '@angular/core';
import { Router } from '@angular/router';
import { AppSvgIconComponent, SearchComponent, SelectComponent, SelectItem } from '@shared/components';

import { AppIconComponent } from '../../../../shared/components/app-icon/app-icon.component';
import { NODE_COLORS, NODE_ICONS } from '../../../../visual-programming/core/enums/node-config';
import { NodeType } from '../../../../visual-programming/core/enums/node-type';
import { SecretUsageFlowItem, SecretUsageFlowNode, SecretUsageSummary } from '../../models/secret-usage.model';

export interface SecretUsageDialogData {
    secretName: string;
    usage: SecretUsageSummary;
}

type NodeTypeFilter = NodeType | null;

const NODE_TYPE_FILTER_ITEMS: SelectItem<NodeTypeFilter>[] = [
    { name: 'All', value: null },
    { name: 'Python Node', value: NodeType.PYTHON },
    { name: 'Classification Decision Table', value: NodeType.CLASSIFICATION_TABLE },
    { name: 'Webhook Node', value: NodeType.WEBHOOK_TRIGGER },
    { name: 'Telegram Node', value: NodeType.TELEGRAM_TRIGGER },
];

const NODE_TYPE_LABELS = new Map<NodeType, string>(
    NODE_TYPE_FILTER_ITEMS.filter((item) => item.value !== null).map((item) => [item.value as NodeType, item.name])
);

@Component({
    selector: 'app-secret-usage-dialog',
    templateUrl: './secret-usage-dialog.component.html',
    styleUrls: ['./secret-usage-dialog.component.scss'],
    imports: [CommonModule, AppSvgIconComponent, AppIconComponent, SearchComponent, SelectComponent],
    animations: [
        trigger('collapseExpand', [
            state('expanded', style({ height: '*', opacity: 1, overflow: 'hidden' })),
            state('collapsed', style({ height: '0', opacity: 0, overflow: 'hidden' })),
            transition('expanded <=> collapsed', animate('200ms ease')),
        ]),
    ],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class SecretUsageDialogComponent {
    private readonly dialogRef = inject(DialogRef<void>);
    private readonly data = inject<SecretUsageDialogData>(DIALOG_DATA);
    private readonly router = inject(Router);

    public readonly secretName = this.data.secretName;
    public readonly usage = this.data.usage;
    public readonly nodeTypeFilterItems = NODE_TYPE_FILTER_ITEMS;

    public readonly expandedFlowName = signal<string | null>(null);
    public readonly nodeSearchTerm = signal<string>('');
    public readonly nodeTypeFilter = signal<NodeTypeFilter>(null);

    public filteredNodes(flow: SecretUsageFlowItem): SecretUsageFlowNode[] {
        const term = this.nodeSearchTerm().toLowerCase().trim();
        const typeFilter = this.nodeTypeFilter();
        return flow.nodes.filter((node) => {
            const matchesTerm = !term || node.name.toLowerCase().includes(term);
            const matchesType = typeFilter === null || node.nodeType === typeFilter;
            return matchesTerm && matchesType;
        });
    }

    public toggleFlow(flowName: string): void {
        if (this.expandedFlowName() === flowName) {
            this.expandedFlowName.set(null);
            return;
        }
        this.expandedFlowName.set(flowName);
        this.nodeSearchTerm.set('');
        this.nodeTypeFilter.set(null);
    }

    public isFlowExpanded(flowName: string): boolean {
        return this.expandedFlowName() === flowName;
    }

    public onNodeTypeFilterChange(value: unknown): void {
        this.nodeTypeFilter.set(value as NodeTypeFilter);
    }

    public nodeIcon(nodeType: NodeType): string {
        return NODE_ICONS[nodeType];
    }

    public nodeColor(nodeType: NodeType): string {
        return NODE_COLORS[nodeType];
    }

    public nodeTypeLabel(nodeType: NodeType): string {
        return NODE_TYPE_LABELS.get(nodeType) ?? '';
    }

    public scrollToCategory(key: string): void {
        document.getElementById(`secret-usage-category-${key}`)?.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }

    public navigateToFlow(flow: SecretUsageFlowItem): void {
        const urlTree = this.router.createUrlTree(['/flows', flow.id]);
        window.open(this.router.serializeUrl(urlTree), '_blank');
    }

    public onClose(): void {
        this.dialogRef.close();
    }
}
