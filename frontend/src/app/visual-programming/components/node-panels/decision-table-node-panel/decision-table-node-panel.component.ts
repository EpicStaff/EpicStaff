import { CommonModule } from '@angular/common';
import { ChangeDetectionStrategy, ChangeDetectorRef, Component, computed, inject, input, signal } from '@angular/core';
import { FormGroup, ReactiveFormsModule } from '@angular/forms';
import { AppSvgIconComponent } from '../../../../shared/components/app-svg-icon/app-svg-icon.component';
import { ConfirmationDialogService } from '../../../../shared/components/cofirm-dialog/confimation-dialog.service';
import { CustomInputComponent } from '../../../../shared/components/form-input/form-input.component';
import { SelectComponent, SelectItem } from '../../../../shared/components/select/select.component';
import { HelpTooltipComponent } from '../../../../shared/components/help-tooltip/help-tooltip.component';
import { NodeType } from '../../../core/enums/node-type';
import { convertDecisionTableToCdt } from '../../../core/helpers/dt-to-cdt-converter';
import { generatePortsForDecisionTableNode } from '../../../core/helpers/helpers';
import { Condition, ConditionGroup, DecisionTableNode } from '../../../core/models/decision-table.model';
import { DecisionTableNodeModel } from '../../../core/models/node.model';
import { BaseSidePanel } from '../../../core/models/node-panel.abstract';
import { FlowService } from '../../../services/flow.service';
import { SidePanelService } from '../../../services/side-panel.service';
import { UndoRedoService } from '../../../services/undo-redo.service';
import { DecisionTableGridComponent } from './decision-table-grid/decision-table-grid.component';

@Component({
    standalone: true,
    selector: 'app-decision-table-node-panel',
    imports: [
        ReactiveFormsModule,
        CustomInputComponent,
        CommonModule,
        DecisionTableGridComponent,
        SelectComponent,
        HelpTooltipComponent,
    ],
    templateUrl: './decision-table-node-panel.component.html',
    styleUrls: ['./decision-table-node-panel.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class DecisionTableNodePanelComponent extends BaseSidePanel<DecisionTableNodeModel> {
    public override readonly isExpanded = input<boolean>(true);
    public readonly graphId = input<number | null>(null);

    private flowService = inject(FlowService);
    private sidePanelService = inject(SidePanelService);
    private confirmationDialogService = inject(ConfirmationDialogService);
    private undoRedoService = inject(UndoRedoService);
    private cdr = inject(ChangeDetectorRef);

    public conditionGroups = signal<ConditionGroup[]>([]);

    public availableNodeItems = computed<SelectItem[]>(() => {
        const nodes = this.flowService.nodes();
        const currentNodeId = this.node().id;

        const nodeItems = nodes
            .filter(
                (node) =>
                    node.type !== NodeType.NOTE &&
                    node.type !== NodeType.START &&
                    node.type !== NodeType.WEBHOOK_TRIGGER &&
                    node.type !== NodeType.TELEGRAM_TRIGGER &&
                    node.id !== currentNodeId
            )
            .map((node) => ({
                value: node.id,
                name: node.node_name || node.id,
            }));

        return [{ name: '-- Select Node --', value: '' }, ...nodeItems];
    });

    get activeColor(): string {
        return this.node().color || '#685fff';
    }

    initializeForm(): FormGroup {
        const node = this.node();
        const decisionTableData = (node.data as Record<string, unknown>)['table'] as DecisionTableNode;
        const nodes = this.flowService.nodes();
        const connections = this.flowService.connections();

        const findNodeId = (value: string | null, role: 'default' | 'error'): string => {
            // 1. Try to find by ID or Name directly
            if (value) {
                const foundNode = nodes.find((n) => n.id === value || n.node_name === value);
                if (foundNode) {
                    return foundNode.id;
                }
                console.warn(`[DecisionTable] Node not found for value: '${value}'`);
            }

            // 2. Fallback: Check visual connections
            // The port ID follows the convention: `${nodeId}_decision-${role}`
            // For default: decision-default
            // For error: decision-error
            const portSuffix = role === 'default' ? 'decision-default' : 'decision-error';
            const portId = `${node.id}_${portSuffix}`;

            const connection = connections.find((c) => c.sourceNodeId === node.id && c.sourcePortId === portId);

            if (connection) {
                return connection.targetNodeId;
            }

            return value || '';
        };

        const defaultNext = findNodeId(decisionTableData.default_next_node, 'default');
        const errorNext = findNodeId(decisionTableData.next_error_node, 'error');

        const form = this.fb.group({
            node_name: [node.node_name, this.createNodeNameValidators()],
            default_next_node: [defaultNext],
            next_error_node: [errorNext],
        });

        const groupsCopy = this.cloneConditionGroups(decisionTableData.condition_groups || []);

        this.conditionGroups.set(groupsCopy);

        return form;
    }

    createUpdatedNode(): DecisionTableNodeModel {
        const currentNode = this.node();
        const conditionGroups = this.cloneConditionGroups(this.conditionGroups() || []);

        const decisionTableData: DecisionTableNode = {
            default_next_node: this.form.value.default_next_node || null,
            next_error_node: this.form.value.next_error_node || null,
            condition_groups: conditionGroups,
        };

        const headerHeight = 60;
        const rowHeight = 46;
        const validGroupsCount = conditionGroups.filter((g) => g.valid).length;
        const hasDefaultRow = 1;
        const hasErrorRow = 1;
        const totalRows = Math.max(validGroupsCount + hasDefaultRow + hasErrorRow, 2);
        const calculatedHeight = headerHeight + rowHeight * totalRows;

        const updatedSize = {
            width: currentNode.size?.width || 330,
            height: Math.max(calculatedHeight, 152),
        };

        const updatedPorts = generatePortsForDecisionTableNode(currentNode.id, conditionGroups);

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
        this.notifyExternalChange();
    }

    public convertToCdt(): void {
        this.confirmationDialogService
            .confirm({
                title: 'Convert to Classification Decision Table?',
                message:
                    'This will replace this Decision Table with a Classification Decision Table. ' +
                    'Per-row connections are preserved by auto-generating a route code for each rule. ' +
                    'This action cannot be undone.',
                confirmText: 'Convert',
                cancelText: 'Cancel',
                type: 'warning',
            })
            .subscribe((result) => {
                if (result !== true) {
                    return;
                }

                // Build from the CURRENT panel state (not this.node(), the committed flow-state node)
                // so uncommitted edits — e.g. a condition just added in the open panel — are included
                // in the conversion. Otherwise converting without closing/saving first drops them.
                const dtNode = this.createUpdatedNode();
                const { node: cdtNode, portIdMap } = convertDecisionTableToCdt(dtNode);

                // Strategy (a): clear selection first so the DT panel unmounts and
                // captureCurrentNodeState() cannot write a stale DT node back into
                // flow state when emitSave() calls commitSidePanelToFlow().
                this.sidePanelService.clearSelection();

                this.flowService.replaceNodePreservingEdges(dtNode.id, cdtNode, {
                    portIdMap,
                });

                // Materialize live canvas edges for ALL converted groups that route via
                // group.next_node. replaceNodePreservingEdges only remaps PRE-EXISTING edges,
                // so a row whose next node was set via the grid "Next Node" dropdown would otherwise have no edge until a
                // reload. Rebuilding from next_node here matches the post-reload behavior.
                const cdtTable = cdtNode.data.table;
                this.flowService.resetDecisionTableConnections(
                    cdtNode.id,
                    cdtTable.condition_groups,
                    cdtTable.default_next_node,
                    cdtTable.next_error_node
                );

                // The conversion is irreversible (see confirm dialog: "This action cannot be undone").
                // Reset undo/redo history so Undo/CTRL+Z can't revert to the pre-conversion DT node,
                // whose stale backendId would otherwise be sent in the save payload and rejected by the
                // backend .
                this.undoRedoService.clear();

                this.sidePanelService.setSelectedNodeId(cdtNode.id);
                this.sidePanelService.requestFullSave();
            });
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
