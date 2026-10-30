import { CdkDrag, CdkDragDrop, CdkDragHandle, CdkDropList, moveItemInArray } from '@angular/cdk/drag-drop';
import {
    afterNextRender,
    ChangeDetectionStrategy,
    Component,
    ElementRef,
    inject,
    Injector,
    input,
    model,
    viewChild,
    viewChildren,
} from '@angular/core';
import { MatTooltip } from '@angular/material/tooltip';
import { AppSvgIconComponent } from '@shared/components';

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
    imports: [
        AuditConditionRowComponent,
        AuditSelectComponent,
        CdkDropList,
        CdkDrag,
        CdkDragHandle,
        AppSvgIconComponent,
        MatTooltip,
    ],
    templateUrl: './audit-condition-filter.component.html',
    styleUrl: './audit-condition-filter.component.scss',
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class AuditConditionFilterComponent {
    public groups = model.required<AuditConditionGroup[]>();
    public operators = input<AuditFilterOp[]>([]);
    public showKey = input<boolean>(true);
    public keyOptions = input<{ value: string; label: string }[]>([]);

    private readonly addConditionButtons = viewChildren<ElementRef<HTMLButtonElement>>('addConditionButton');
    private readonly addGroupButton = viewChild.required<ElementRef<HTMLButtonElement>>('addGroupButton');

    protected readonly joinOptions = JOIN_OPTIONS;

    private readonly injector = inject(Injector);

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
        // the remove button goes with its row: the focus moves to its group's Add condition, or to Add group when the
        // group went with its last row
        afterNextRender(
            () =>
                (
                    this.addConditionButtons().find((button) => button.nativeElement.dataset['groupId'] === groupId) ??
                    this.addGroupButton()
                ).nativeElement.focus(),
            { injector: this.injector }
        );
    }

    protected reorderCondition(groupId: string, event: CdkDragDrop<AuditCondition[]>): void {
        if (event.previousIndex === event.currentIndex) {
            return;
        }
        this.updateGroup(groupId, (group) => {
            const conditions = [...group.conditions];
            moveItemInArray(conditions, event.previousIndex, event.currentIndex);
            return { ...group, conditions };
        });
    }

    private updateGroup(groupId: string, change: (group: AuditConditionGroup) => AuditConditionGroup): void {
        this.groups.update((current) => current.map((group) => (group.id === groupId ? change(group) : group)));
    }
}
