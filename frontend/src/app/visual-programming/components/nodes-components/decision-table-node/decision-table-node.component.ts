import { CommonModule, NgStyle } from '@angular/common';
import { ChangeDetectionStrategy, Component, EventEmitter, inject, Input, Output } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { FFlowModule } from '@foblex/flow';
import { formatNodeLabel } from '@shared/utils';

import { ClickOrDragDirective } from '../../../core/directives/click-or-drag.directive';
import { routePortsWithoutRow } from '../../../core/helpers/helpers';
import { showsNodeNumber } from '../../../core/helpers/node-number.util';
import { DT_HEADER_HEIGHT, DT_ROW_HEIGHT } from '../../../core/helpers/node-size.util';
import { ConditionGroup } from '../../../core/models/decision-table.model';
import { DecisionTableNodeModel } from '../../../core/models/node.model';
import { CustomPortId, ViewPort } from '../../../core/models/port.model';
import { FlowService } from '../../../services/flow.service';
import { FlowDiffStateService } from '../../../services/flow-diff-state.service';
import { FlowReadOnlyService } from '../../../services/flow-readonly.service';
import { FlowSettingsService } from '../../../services/flow-settings.service';
@Component({
    selector: 'app-decision-table-node',
    templateUrl: './decision-table-node.component.html',
    styleUrls: ['./decision-table-node.component.scss'],
    imports: [CommonModule, FormsModule, ClickOrDragDirective, FFlowModule, NgStyle],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class DecisionTableNodeComponent {
    @Input({ required: true }) node!: DecisionTableNodeModel;
    @Output() actualClick = new EventEmitter<MouseEvent>();

    private flowService = inject(FlowService);
    private readonly flowSettings = inject(FlowSettingsService);
    public readonly isReadOnly = inject(FlowReadOnlyService).isReadOnly;
    private readonly flowDiffState = inject(FlowDiffStateService);

    public readonly headerHeightPx = DT_HEADER_HEIGHT;
    public readonly rowHeightPx = DT_ROW_HEIGHT;
    protected readonly addedRouteLabel = 'Restore adds this condition';

    public getPortConnections(portId: CustomPortId): CustomPortId[] {
        return this.flowService.portConnectionsMap()[portId] ?? ['__none__'];
    }

    get conditionGroups(): ConditionGroup[] {
        const allGroups = this.node.data.table?.condition_groups ?? [];
        return allGroups
            .filter((group) => group.valid !== false)
            .sort((a, b) => (a.order ?? Number.MAX_SAFE_INTEGER) - (b.order ?? Number.MAX_SAFE_INTEGER));
    }

    /** On a version diff canvas: the routes only the current canvas has, which a restore removes. */
    get removedRoutePorts(): ViewPort[] {
        if (!this.flowDiffState.isActive()) return [];
        const rowPortIds = new Set(
            this.conditionGroups.map((group) => this.getPortForGroup(group)?.id).filter((id) => id !== undefined)
        );
        return routePortsWithoutRow(this.node.ports, rowPortIds);
    }

    /** On a version diff canvas: whether the group's route is only in the version, so a restore adds it. */
    protected isAddedRoute(group: ConditionGroup): boolean {
        const port = this.getPortForGroup(group);
        return !!port && this.flowDiffState.isVersionOnlyPort(port.id);
    }

    get defaultNextNode() {
        return this.node.data.table?.default_next_node;
    }

    get defaultNextNodeName(): string | null {
        const idOrName = this.defaultNextNode;
        if (!idOrName) return null;
        const nodes = this.flowService.nodes();
        const node = nodes.find((n) => n.id === idOrName || n.node_name === idOrName);
        return node ? formatNodeLabel(node) : idOrName;
    }

    get nextErrorNode() {
        return this.node.data.table?.next_error_node;
    }

    get nextErrorNodeName(): string | null {
        const idOrName = this.nextErrorNode;
        if (!idOrName) return null;
        const nodes = this.flowService.nodes();
        const node = nodes.find((n) => n.id === idOrName || n.node_name === idOrName);
        return node ? formatNodeLabel(node) : idOrName;
    }

    get title(): string {
        return this.node.node_name || 'Decision Table';
    }

    /** Whether the header shows the node's "#N" under the title. */
    protected get isNumberedNode(): boolean {
        return showsNodeNumber(this.node);
    }

    /** The "#N" stays shown under the title; otherwise it appears on hover. */
    protected get isNodeNumberPinned(): boolean {
        return this.isNumberedNode && this.flowSettings.alwaysShowNodeNumbers();
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

    trackConditionGroup(index: number, group: ConditionGroup): string {
        const port = this.getPortForGroup(group);
        if (port) {
            return port.id;
        }

        if (group.group_name) {
            return group.group_name;
        }

        return String(index);
    }

    getPortForGroup(group: ConditionGroup) {
        const role = this.getRoleForGroup(group);
        if (!role) {
            return undefined;
        }

        return this.node.ports?.find((p) => p.role === role);
    }

    onEditClick() {
        this.actualClick.emit();
    }

    private getRoleForGroup(group: ConditionGroup): string | undefined {
        const groupName = group.group_name?.trim();
        if (!groupName) {
            return undefined;
        }

        return `decision-out-${groupName}`;
    }
}
