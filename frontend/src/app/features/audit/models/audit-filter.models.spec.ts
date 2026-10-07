import { AuditConditionGroup, createAuditCondition, removeAuditCondition } from './audit-filter.models';

function group(id: string, ...conditionIds: string[]): AuditConditionGroup {
    return {
        id,
        join: 'and',
        conditions: conditionIds.map((conditionId) => ({ ...createAuditCondition(), id: conditionId })),
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
