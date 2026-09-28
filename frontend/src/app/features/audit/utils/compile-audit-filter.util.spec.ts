import {
    AuditConditionGroup,
    AuditConditionJoin,
    createAuditCondition,
    EMPTY_AUDIT_FILTER,
} from '../models/audit-filter.models';
import { compileAuditFilter } from './compile-audit-filter.util';
import { describeAuditFilter } from './describe-audit-filter.util';

function group(join: AuditConditionJoin, ...values: string[]): AuditConditionGroup {
    return { id: values.join('-'), join, conditions: values.map((value) => ({ ...createAuditCondition(), value })) };
}

const leaf = (value: string) => ({ field: 'input', op: 'contains', value });

describe('audit condition groups', () => {
    it('compiles a single group exactly like the old flat list', () => {
        const { filters } = compileAuditFilter({ ...EMPTY_AUDIT_FILTER, input: [group('or', 'a', 'b')] });
        expect(filters).toEqual({ op: 'and', children: [leaf('a'), leaf('b')] });
    });

    it('joins groups by the group join and ignores the first group join', () => {
        const { filters } = compileAuditFilter({
            ...EMPTY_AUDIT_FILTER,
            input: [group('and', 'a', 'b'), group('or', 'c')],
        });
        expect(filters).toEqual({
            op: 'or',
            children: [{ op: 'and', children: [leaf('a'), leaf('b')] }, leaf('c')],
        });
    });

    it('skips a group with no usable condition', () => {
        const { filters } = compileAuditFilter({ ...EMPTY_AUDIT_FILTER, input: [group('and', ''), group('or', 'c')] });
        expect(filters).toEqual(leaf('c'));
    });

    it('brackets compound groups in the chip', () => {
        const chips = describeAuditFilter({ ...EMPTY_AUDIT_FILTER, input: [group('and', 'a', 'b'), group('or', 'c')] });
        expect(chips.find((chip) => chip.key === 'input')?.value).toBe('(contains a AND contains b) OR contains c');
    });

    it('folds three groups left to right in both the chip and the compiled tree', () => {
        const state = { ...EMPTY_AUDIT_FILTER, input: [group('and', 'a', 'b'), group('or', 'c'), group('and', 'd')] };
        const chips = describeAuditFilter(state);
        expect(chips.find((chip) => chip.key === 'input')?.value).toBe(
            '((contains a AND contains b) OR contains c) AND contains d'
        );
        expect(compileAuditFilter(state).filters).toEqual({
            op: 'and',
            children: [{ op: 'or', children: [{ op: 'and', children: [leaf('a'), leaf('b')] }, leaf('c')] }, leaf('d')],
        });
    });
});
