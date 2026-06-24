import { CommonModule, NgStyle } from '@angular/common';
import { ChangeDetectionStrategy, Component, DestroyRef, EventEmitter, inject, Input, Output } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { FormsModule } from '@angular/forms';
import { FFlowModule } from '@foblex/flow';
import { LlmConfigStorageService } from '@shared/services';

import { ClickOrDragDirective } from '../../../core/directives/click-or-drag.directive';
import { ConditionGroup } from '../../../core/models/decision-table.model';
import { ClassificationDecisionTableNodeModel } from '../../../core/models/node.model';
import { ViewPort } from '../../../core/models/port.model';
import { FlowService } from '../../../services/flow.service';

@Component({
    selector: 'app-classification-decision-table-node',
    templateUrl: './classification-decision-table-node.component.html',
    styleUrls: ['./classification-decision-table-node.component.scss'],
    standalone: true,
    imports: [CommonModule, FormsModule, ClickOrDragDirective, FFlowModule, NgStyle],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class ClassificationDecisionTableNodeComponent {
    @Input({ required: true }) node!: ClassificationDecisionTableNodeModel;
    @Output() actualClick = new EventEmitter<MouseEvent>();

    private flowService = inject(FlowService);
    private readonly llmConfigStorageService = inject(LlmConfigStorageService);
    private readonly destroyRef = inject(DestroyRef);

    constructor() {
        this.llmConfigStorageService.getAllConfigs().pipe(takeUntilDestroyed(this.destroyRef)).subscribe();
    }

    get conditionGroups(): ConditionGroup[] {
        const allGroups = this.node.data.table?.condition_groups ?? [];
        return allGroups
            .filter((group: ConditionGroup) => group.valid !== false && group.dock_visible)
            .sort(
                (a: ConditionGroup, b: ConditionGroup) =>
                    (a.order ?? Number.MAX_SAFE_INTEGER) - (b.order ?? Number.MAX_SAFE_INTEGER)
            );
    }

    get defaultNextNode() {
        return this.node.data.table?.default_next_node;
    }

    get defaultNextNodeName(): string | null {
        const idOrName = this.defaultNextNode;
        if (!idOrName) return null;
        const nodes = this.flowService.nodes();
        const node = nodes.find((n) => n.id === idOrName || n.node_name === idOrName);
        return node ? node.node_name : idOrName;
    }

    get nextErrorNode() {
        return this.node.data.table?.next_error_node;
    }

    get nextErrorNodeName(): string | null {
        const idOrName = this.nextErrorNode;
        if (!idOrName) return null;
        const nodes = this.flowService.nodes();
        const node = nodes.find((n) => n.id === idOrName || n.node_name === idOrName);
        return node ? node.node_name : idOrName;
    }

    get inputPort() {
        return this.node.ports?.find((p) => p.port_type === 'input');
    }

    get defaultPort() {
        return this.node.ports?.find((p) => p.role === 'decision-default');
    }

    get errorPort() {
        return this.node.ports?.find((p) => p.role === 'decision-error');
    }

    trackRouteDock(index: number, dock: { code: string; port: ViewPort | undefined }): string {
        return dock.code;
    }

    getPortForRouteCode(routeCode: string) {
        const role = `decision-route-${routeCode}`;
        return this.node.ports?.find((p) => p.role === role);
    }

    trackConditionGroup(index: number, group: ConditionGroup): string {
        const port = this.getPortForGroup(group);
        if (port) {
            return `${index}:${port.id}`;
        }
        if (group.group_name) {
            return `${index}:${group.group_name}`;
        }
        return String(index);
    }

    getPortForGroup(group: ConditionGroup) {
        const key = group.route_code || group.group_name;
        if (!key) {
            return undefined;
        }
        return this.node.ports?.find((p) => p.role === `decision-route-${key}`);
    }

    get hasMissingLlmConfig(): boolean {
        const table = this.node.data.table;
        if (!table) return false;

        // A prompt with no LLM config selected is always considered missing,
        // regardless of whether the available-configs list has loaded yet.
        if (table.prompts) {
            for (const prompt of Object.values(table.prompts) as Array<{ llm_config: number | null }>) {
                if (prompt.llm_config == null) return true;
            }
        }

        // Deleted-config detection requires the configs list to be loaded.
        if (!this.llmConfigStorageService.isConfigsLoaded()) return false;
        const availableIds = new Set(this.llmConfigStorageService.configs().map((c) => c.id));

        if (table.default_llm_config != null && !availableIds.has(table.default_llm_config)) {
            return true;
        }
        if (table.prompts) {
            for (const prompt of Object.values(table.prompts) as Array<{ llm_config: number | null }>) {
                if (prompt.llm_config != null && !availableIds.has(prompt.llm_config)) return true;
            }
        }
        return false;
    }

    onEditClick() {
        this.actualClick.emit();
    }
}
