import { CommonModule, NgStyle } from '@angular/common';
import { ChangeDetectionStrategy, Component, EventEmitter, inject, Input, Output } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { FFlowModule } from '@foblex/flow';

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

    get conditionGroups(): ConditionGroup[] {
        const allGroups = this.node.data.table?.condition_groups ?? [];
        return allGroups
            .filter((group: ConditionGroup) => group.valid !== false && group.dock_visible)
            .sort(
                (a: ConditionGroup, b: ConditionGroup) =>
                    (a.order ?? Number.MAX_SAFE_INTEGER) - (b.order ?? Number.MAX_SAFE_INTEGER)
            );
    }

    // get routeDocks(): Array<{ code: string; port: ViewPort | undefined }> {
    //     const allGroups = this.node.data.table?.condition_groups ?? [];
    //     const uniqueRouteCodes = new Map<string, ViewPort | undefined>();

    //     // Collect unique route codes where dock_visible=true
    //     allGroups.forEach((group: ConditionGroup) => {
    //         if (group.route_code && group.dock_visible) {
    //             if (!uniqueRouteCodes.has(group.route_code)) {
    //                 const port = this.getPortForRouteCode(group.route_code);
    //                 uniqueRouteCodes.set(group.route_code, port);
    //             }
    //         }
    //     });

    //     return Array.from(uniqueRouteCodes.entries()).map(([code, port]) => ({
    //         code,
    //         port,
    //     }));
    // }

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
            return port.id;
        }
        if (group.group_name) {
            return group.group_name;
        }
        return String(index);
    }

    getPortForGroup(group: ConditionGroup) {
        const groupName = group.group_name?.trim();
        if (!groupName) {
            return undefined;
        }
        return this.node.ports?.find((p) => p.role === `decision-out-${groupName}`);
    }

    onEditClick() {
        this.actualClick.emit();
    }
}
