import { TestBed } from '@angular/core/testing';

import { AuditConditionGroup, AuditFilterOp, createAuditConditionGroup } from '../../models/audit-filter.models';
import { USER_ACTION_TYPE_OPERATORS } from '../../models/audit-user-action-filter-options';
import { AuditConditionFilterComponent } from './audit-condition-filter.component';

function render(groups: AuditConditionGroup[], operators: AuditFilterOp[]) {
    const fixture = TestBed.createComponent(AuditConditionFilterComponent);
    fixture.componentRef.setInput('groups', groups);
    fixture.componentRef.setInput('operators', operators);
    fixture.componentRef.setInput('showKey', false);
    fixture.detectChanges();
    const element = fixture.nativeElement as HTMLElement;
    const click = (label: string) => {
        const button = Array.from(element.querySelectorAll('button')).find(
            (item) => item.textContent?.trim() === label
        );
        button?.click();
        fixture.detectChanges();
    };
    const ops = () =>
        fixture.componentInstance.groups().map((group) => group.conditions.map((condition) => condition.op));
    return { element, click, ops };
}

describe('AuditConditionFilterComponent', () => {
    it('starts an added condition and an added group with the first operator of a field offering no contains', () => {
        const { click, ops } = render(
            [createAuditConditionGroup(USER_ACTION_TYPE_OPERATORS)],
            USER_ACTION_TYPE_OPERATORS
        );

        click('+ Add condition');
        click('+ Add group');

        expect(ops()).toEqual([['equals', 'equals'], ['equals']]);
    });

    it('still renders a condition saved with an operator the field no longer offers', () => {
        const saved: AuditConditionGroup = {
            id: 'group',
            join: 'or',
            conditions: [{ id: 'condition', join: 'and', key: '', op: 'contains', value: 'flow' }],
        };

        const { element } = render([saved], USER_ACTION_TYPE_OPERATORS);

        expect(element.querySelectorAll('app-audit-condition-row')).toHaveLength(1);
    });
});
