import {
    ChangeDetectionStrategy,
    Component,
    input,
    ChangeDetectorRef,
    signal,
    computed,
    inject,
    effect,
} from '@angular/core';
import { ReactiveFormsModule, FormGroup, Validators } from '@angular/forms';
import { DecisionTableNodeModel } from '../../../core/models/node.model';
import { BaseSidePanel } from '../../../core/models/node-panel.abstract';
import { CustomInputComponent } from '../../../../shared/components/form-input/form-input.component';
import { CommonModule } from '@angular/common';
import {
    DecisionTableNode,
    ConditionGroup,
    Condition,
} from '../../../core/models/decision-table.model';
import { DecisionTableGridComponent } from './decision-table-grid/decision-table-grid.component';
import { FlowService } from '../../../services/flow.service';
import { NodeType } from '../../../core/enums/node-type';
import { generatePortsForDecisionTableNode } from '../../../core/helpers/helpers';

@Component({
    standalone: true,
    selector: 'app-decision-table-node-panel',
    imports: [
        ReactiveFormsModule,
        CustomInputComponent,
        CommonModule,
        DecisionTableGridComponent,
    ],
    templateUrl: './decision-table-node-panel.component.html',
    styleUrls: ['./decision-table-node-panel.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class DecisionTableNodePanelComponent extends BaseSidePanel<DecisionTableNodeModel> {
    public readonly isExpanded = input<boolean>(true);

    private flowService = inject(FlowService);
    private cdr = inject(ChangeDetectorRef);

    public conditionGroups = signal<ConditionGroup[]>([]);

    public availableNodes = computed(() => {
        const nodes = this.flowService.nodes();
        const currentNodeId = this.node().id;
        
        return nodes
            .filter((node) => 
                node.type !== NodeType.NOTE && 
                node.type !== NodeType.START &&
                node.type !== NodeType.WEBHOOK_TRIGGER &&
                node.id !== currentNodeId
            )
            .map((node) => ({
                value: node.node_name || node.id,
                label: node.node_name || node.id,
            }));
    });

    get activeColor(): string {
        return this.node().color || '#685fff';
    }

    initializeForm(): FormGroup {
        const node = this.node();
        const decisionTableData = (node.data as any).table as DecisionTableNode;

        const form = this.fb.group({
            node_name: [node.node_name, this.createNodeNameValidators()],
            default_next_node: [decisionTableData.default_next_node || ''],
            next_error_node: [decisionTableData.next_error_node || ''],
        });

        const groupsCopy = this.cloneConditionGroups(
            decisionTableData.condition_groups || []
        );

        this.conditionGroups.set(groupsCopy);

        return form;
    }

    createUpdatedNode(): DecisionTableNodeModel {
        const currentNode = this.node();
        const conditionGroups = this.cloneConditionGroups(
            this.conditionGroups() || []
        );

        const decisionTableData: DecisionTableNode = {
            default_next_node: this.form.value.default_next_node || null,
            next_error_node: this.form.value.next_error_node || null,
            condition_groups: conditionGroups,
        };

        const headerHeight = 60;
        const rowHeight = 46;
        const validGroupsCount = conditionGroups.filter(g => g.valid).length;
        const hasDefaultRow = 1;
        const hasErrorRow = 1;
        const totalRows = Math.max(
            validGroupsCount + hasDefaultRow + hasErrorRow,
            2
        );
        const calculatedHeight = headerHeight + rowHeight * totalRows;

        const updatedSize = {
            width: currentNode.size?.width || 330,
            height: Math.max(calculatedHeight, 152),
        };

        const updatedPorts = generatePortsForDecisionTableNode(
            currentNode.id,
            conditionGroups,
            !!decisionTableData.default_next_node,
            !!decisionTableData.next_error_node
        );

        return {
            ...currentNode,
            node_name: this.form.value.node_name,
            size: updatedSize,
            ports: updatedPorts,
            data: {
                name: this.form.value.node_name || 'Decision Table',
                table: decisionTableData,
            },
        };
    }

    public onConditionGroupsChange(groups: ConditionGroup[]): void {
        this.conditionGroups.set(this.cloneConditionGroups(groups));
        this.cdr.markForCheck();
    }

    private cloneConditionGroups(groups: ConditionGroup[]): ConditionGroup[] {
        return groups.map((group) => ({
            ...group,
            conditions: (group.conditions || []).map((condition: Condition) => ({
                ...condition,
            })),
        }));
    }
}
