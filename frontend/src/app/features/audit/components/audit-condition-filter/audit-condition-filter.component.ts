import { ChangeDetectionStrategy, Component, input, model } from '@angular/core';

import {
    AuditCondition,
    AuditConditionGroup,
    AuditConditionJoin,
    AuditFilterOp,
    createAuditCondition,
    createAuditConditionGroup,
    removeAuditCondition,
} from '../../models/audit-filter.models';
import { JOIN_OPTIONS } from '../../models/audit-filter-options';
import { AuditConditionRowComponent } from '../audit-condition-row/audit-condition-row.component';
import { AuditSelectComponent } from '../audit-select/audit-select.component';

@Component({
    selector: 'app-audit-condition-filter',
    standalone: true,
    imports: [AuditConditionRowComponent, AuditSelectComponent],
    templateUrl: './audit-condition-filter.component.html',
    styleUrl: './audit-condition-filter.component.scss',
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class AuditConditionFilterComponent {
    public groups = model.required<AuditConditionGroup[]>();
    public operators = input<AuditFilterOp[]>([]);
    public showKey = input<boolean>(true);

    protected readonly joinOptions = JOIN_OPTIONS;

    protected addGroup(): void {
        this.groups.update((current) => [...current, createAuditConditionGroup()]);
    }

    protected setGroupJoin(groupId: string, value: string): void {
        const join = value as AuditConditionJoin;
        this.updateGroup(groupId, (group) => ({ ...group, join }));
    }

    protected addCondition(groupId: string): void {
        this.updateGroup(groupId, (group) => ({ ...group, conditions: [...group.conditions, createAuditCondition()] }));
    }

    protected updateCondition(groupId: string, next: AuditCondition): void {
        this.updateGroup(groupId, (group) => ({
            ...group,
            conditions: group.conditions.map((item) => (item.id === next.id ? next : item)),
        }));
    }

    protected removeCondition(groupId: string, conditionId: string): void {
        this.groups.update((current) => removeAuditCondition(current, groupId, conditionId));
    }

    private updateGroup(groupId: string, change: (group: AuditConditionGroup) => AuditConditionGroup): void {
        this.groups.update((current) => current.map((group) => (group.id === groupId ? change(group) : group)));
    }
}
