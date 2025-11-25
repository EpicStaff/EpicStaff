import {
    Component,
    Input,
    Output,
    EventEmitter,
    ChangeDetectionStrategy,
} from '@angular/core';
import { CommonModule, NgStyle } from '@angular/common';
import { DecisionTableNodeModel } from '../../../core/models/node.model';
import { ConditionGroup } from '../../../core/models/decision-table.model';
import { FormsModule } from '@angular/forms';
import { ClickOrDragDirective } from '../../../core/directives/click-or-drag.directive';
import { FFlowModule } from '@foblex/flow';

@Component({
    selector: 'app-decision-table-node',
    templateUrl: './decision-table-node.component.html',
    styleUrls: ['./decision-table-node.component.scss'],
    standalone: true,
    imports: [CommonModule, FormsModule, ClickOrDragDirective, FFlowModule, NgStyle],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class DecisionTableNodeComponent {
    @Input({ required: true }) node!: DecisionTableNodeModel;
    @Output() actualClick = new EventEmitter<MouseEvent>();

    get conditionGroups(): ConditionGroup[] {
        const allGroups = this.node.data.table?.condition_groups ?? [];
        return allGroups
            .filter((group) => group.valid !== false)
            .sort(
                (a, b) =>
                    (a.order ?? Number.MAX_SAFE_INTEGER) -
                    (b.order ?? Number.MAX_SAFE_INTEGER)
            );
    }

    get defaultNextNode() {
        return this.node.data.table?.default_next_node;
    }

    get nextErrorNode() {
        return this.node.data.table?.next_error_node;
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
