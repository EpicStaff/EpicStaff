import { AuditTextField } from './audit-domain.models';
import {
    AuditConditionGroup,
    AuditFilterOp,
    AuditFilterState,
    catalogTextConditions,
    createAuditCondition,
    createAuditConditionGroup,
    EMPTY_AUDIT_FILTER,
    removeAuditCondition,
} from './audit-filter.models';
import { DEEP_TEXT_OPERATORS, ERROR_OPERATORS, JSON_OPERATORS } from './audit-filter-options';
import { USER_ACTION_FIELD_CATALOG } from './audit-user-action-filter-options';

function group(id: string, ...conditionIds: string[]): AuditConditionGroup {
    return {
        id,
        join: 'and',
        conditions: conditionIds.map((conditionId) => ({ ...createAuditCondition(['contains']), id: conditionId })),
    };
}

describe('removeAuditCondition', () => {
    it('drops a group whose last row is removed when other groups remain', () => {
        const result = removeAuditCondition([group('g1', 'a'), group('g2', 'b')], 'g1', 'a');
        expect(result.map((item) => item.id)).toEqual(['g2']);
    });

    it('keeps the only group with no rows when its last row is removed', () => {
        const result = removeAuditCondition([group('g1', 'a')], 'g1', 'a');
        expect(result).toHaveLength(1);
        expect(result[0].id).toBe('g1');
        expect(result[0].conditions).toEqual([]);
    });

    it('always leaves exactly one group when every last row is removed one by one', () => {
        let groups = [group('g1', 'a'), group('g2', 'b'), group('g3', 'c')];
        for (const [groupId, conditionId] of [
            ['g1', 'a'],
            ['g2', 'b'],
            ['g3', 'c'],
        ]) {
            groups = removeAuditCondition(groups, groupId, conditionId);
            expect(groups.length).toBeGreaterThanOrEqual(1);
        }
        expect(groups).toHaveLength(1);
        expect(groups[0].conditions).toEqual([]);
    });

    it('only removes the row from the given group', () => {
        const result = removeAuditCondition([group('g1', 'same', 'x'), group('g2', 'same')], 'g1', 'same');
        expect(result.map((item) => item.conditions.map((condition) => condition.id))).toEqual([['x'], ['same']]);
    });
});

describe('createAuditConditionGroup', () => {
    it('joins a new group to the previous one with OR, in a fresh builder too', () => {
        expect(createAuditConditionGroup(JSON_OPERATORS).join).toBe('or');
        expect(EMPTY_AUDIT_FILTER.input[0].join).toBe('or');
    });
});

describe('a new condition', () => {
    it('starts with equals on a field offering no contains', () => {
        const wholeValueOperators: AuditFilterOp[] = ['equals', 'not_equal'];

        expect(createAuditCondition(wholeValueOperators).op).toBe('equals');
        expect(createAuditConditionGroup(wholeValueOperators).conditions.map((item) => item.op)).toEqual(['equals']);
    });
});

// A condition carrying an operator its field does not offer is still sent, and the backend rejects it.
describe('the starting condition of every Builder text field', () => {
    const startingOps = (groups: AuditConditionGroup[]) =>
        groups.flatMap((group) => group.conditions.map((condition) => condition.op));

    const userActionTextFields = USER_ACTION_FIELD_CATALOG.builderFields.filter(
        (item): item is AuditTextField => item.kind === 'text'
    );

    it.each(userActionTextFields.map((item) => [item.field, item] as const))(
        'user actions %s starts with an operator it offers',
        (_field, textField) => {
            const ops = startingOps(catalogTextConditions(EMPTY_AUDIT_FILTER, textField));

            expect(ops).toHaveLength(1);
            expect(textField.operators).toContain(ops[0]);
        }
    );

    // the operators each sessions condition field offers, as its filter in the panel is given them
    const sessionFieldOperators: Record<string, AuditFilterOp[]> = {
        error: ERROR_OPERATORS,
        input: JSON_OPERATORS,
        output: JSON_OPERATORS,
        details: JSON_OPERATORS,
        task: DEEP_TEXT_OPERATORS,
        prompt: DEEP_TEXT_OPERATORS,
        messageText: DEEP_TEXT_OPERATORS,
    };

    it('lists every sessions condition field, so a new one cannot skip this check', () => {
        const conditionFields = Object.entries(EMPTY_AUDIT_FILTER)
            .filter(
                ([, value]: [string, unknown]) =>
                    Array.isArray(value) &&
                    value.some((item: unknown) => typeof item === 'object' && item !== null && 'conditions' in item)
            )
            .map(([key]) => key);

        expect(conditionFields.sort()).toEqual(Object.keys(sessionFieldOperators).sort());
    });

    it.each(Object.entries(sessionFieldOperators))(
        'sessions %s starts with an operator it offers',
        (key, operators) => {
            const ops = startingOps(EMPTY_AUDIT_FILTER[key as keyof AuditFilterState] as AuditConditionGroup[]);

            expect(ops).toHaveLength(1);
            expect(operators).toContain(ops[0]);
        }
    );
});
