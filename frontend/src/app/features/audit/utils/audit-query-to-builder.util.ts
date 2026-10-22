import {
    AuditCondition,
    AuditConditionGroup,
    AuditConditionJoin,
    AuditEnumOption,
    AuditFilterLeaf,
    AuditFilterNode,
    AuditFilterOp,
    AuditFilterState,
    AuditValuesFilter,
    createAuditCondition,
    createAuditConditionGroup,
    EMPTY_AUDIT_FILTER,
    FREE_TEXT_FIELD,
    VALUE_FREE_OPS,
} from '../models/audit-filter.models';
import {
    DEEP_TEXT_OPERATORS,
    ERROR_OPERATORS,
    JSON_OPERATORS,
    KIND_OPTIONS,
    NODE_TYPE_OPTIONS,
    STATUS_OPTIONS,
    TOKEN_OPERATORS,
} from '../models/audit-filter-options';
import { AuditEventKind, AuditEventStatus, AuditNodeType } from '../models/audit-session.models';
import { AUDIT_FILTER_FIELDS, isFieldAvailable } from './audit-filter-compatibility.util';
import { AuditQueryParseError, parseAuditQuery } from './audit-query-language.util';
import { compileAuditFilter, TOKENS_FIELD, TOOL_NAME_FIELD } from './compile-audit-filter.util';

type ConditionStateKey = 'error' | 'input' | 'output' | 'details' | 'task' | 'prompt' | 'messageText';

interface ConditionField {
    stateKey: ConditionStateKey;
    operators: AuditFilterOp[];
    // only the JSON roots let the Builder pick a key below the root
    hasKey: boolean;
}

const CONDITION_FIELDS = new Map<string, ConditionField>([
    ['error', { stateKey: 'error', operators: ERROR_OPERATORS, hasKey: false }],
    ['input', { stateKey: 'input', operators: JSON_OPERATORS, hasKey: true }],
    ['output', { stateKey: 'output', operators: JSON_OPERATORS, hasKey: true }],
    ['details', { stateKey: 'details', operators: JSON_OPERATORS, hasKey: true }],
    ['task', { stateKey: 'task', operators: DEEP_TEXT_OPERATORS, hasKey: false }],
    ['prompt', { stateKey: 'prompt', operators: DEEP_TEXT_OPERATORS, hasKey: false }],
    ['message_text', { stateKey: 'messageText', operators: DEEP_TEXT_OPERATORS, hasKey: false }],
]);

const SELECT_FIELDS = ['kind', 'status', 'node_type', 'flow_name', 'agent', 'tool'];
// the NUMBER token of the query language - only such strings may stand in for a compiled number
const NUMBER_TEXT = /^\d+(\.\d+)?$/;

function isLeaf(node: AuditFilterNode): node is AuditFilterLeaf {
    return 'field' in node;
}

// The one place where two filters count as "the same": nested same-op groups are flattened
// (associativity), `= v` / `!= v` on select fields become `in [v]` / `not in [v]`, `tool` becomes
// its compiled details.data.name form, and `!=` becomes key_not_equals on condition fields that offer it.
function canonical(node: AuditFilterNode): AuditFilterNode {
    if ('children' in node) {
        const children = node.children
            .map(canonical)
            .flatMap((child) => ('children' in child && child.op === node.op ? child.children : [child]));
        return { op: node.op, children };
    }
    if (node.op === 'not') {
        return { op: 'not', child: canonical(node.child) };
    }
    const { op, value } = node;
    const field = normalizeFieldName(node.field);
    if (SELECT_FIELDS.includes(field) && (op === 'equals' || op === 'not_equal')) {
        return canonical({ field, op: op === 'equals' ? 'in' : 'not_in', value: [value] });
    }
    if (field === 'tool' && (op === 'in' || op === 'not_in') && Array.isArray(value)) {
        const leaves: AuditFilterNode[] = value.map((name) => ({ field: TOOL_NAME_FIELD, op: 'equals', value: name }));
        const anyOf = leaves.length === 1 ? leaves[0] : { op: 'or' as const, children: leaves };
        return op === 'in' ? anyOf : { op: 'not', child: anyOf };
    }
    if (op === 'not_equal' && CONDITION_FIELDS.get(field.split('.')[0])?.operators.includes('key_not_equals')) {
        return { field, op: 'key_not_equals', value };
    }
    return { field, op, value };
}

// The backend matches field names case-insensitively, but only the root: the keys below a
// JSON root (input.OrderId) are case-sensitive and stay as typed.
function normalizeFieldName(field: string): string {
    const [root, ...path] = field.split('.');
    return [root.toLowerCase(), ...path].join('.');
}

function sameValue(left: unknown, right: unknown): boolean {
    if (Array.isArray(left) && Array.isArray(right)) {
        return left.length === right.length && left.every((item, index) => sameValue(item, right[index]));
    }
    if (typeof left === 'number' && typeof right === 'string') {
        return NUMBER_TEXT.test(right) && Number(right) === left;
    }
    if (typeof left === 'string' && typeof right === 'number') {
        return sameValue(right, left);
    }
    return left === right;
}

function sameNode(left: AuditFilterNode, right: AuditFilterNode): boolean {
    if (isLeaf(left) || isLeaf(right)) {
        return (
            isLeaf(left) &&
            isLeaf(right) &&
            left.field === right.field &&
            left.op === right.op &&
            sameValue(left.value, right.value)
        );
    }
    if (left.op === 'not' || right.op === 'not') {
        return left.op === 'not' && right.op === 'not' && sameNode(left.child, right.child);
    }
    return (
        left.op === right.op &&
        left.children.length === right.children.length &&
        left.children.every((child, index) => sameNode(child, right.children[index]))
    );
}

function conjunctsOf(node: AuditFilterNode): AuditFilterNode[] {
    return 'children' in node && node.op === 'and' ? node.children : [node];
}

// top-level AND is order-insensitive, everything below it must match exactly
function sameConjuncts(left: AuditFilterNode, right: AuditFilterNode): boolean {
    const unmatched = [...conjunctsOf(right)];
    for (const node of conjunctsOf(left)) {
        const index = unmatched.findIndex((other) => sameNode(node, other));
        if (index === -1) {
            return false;
        }
        unmatched.splice(index, 1);
    }
    return unmatched.length === 0;
}

function isOptionList(values: string[], options: AuditEnumOption[]): boolean {
    return values.every((value) => options.some((option) => option.value === value));
}

// `tool` in its compiled form: details.data.name = v, an OR of those, or NOT around either
function toolSelection(node: AuditFilterNode): AuditValuesFilter | null {
    if (!isLeaf(node) && node.op === 'not') {
        const inner = toolSelection(node.child);
        return inner?.op === 'in' ? { op: 'not_in', values: inner.values } : null;
    }
    const leaves = isLeaf(node) ? [node] : node.op === 'or' ? node.children : [];
    const values: string[] = [];
    for (const leaf of leaves) {
        if (!isLeaf(leaf) || leaf.field !== TOOL_NAME_FIELD || leaf.op !== 'equals' || typeof leaf.value !== 'string') {
            return null;
        }
        values.push(leaf.value);
    }
    return values.length > 0 ? { op: 'in', values } : null;
}

// Fills the Builder field this conjunct belongs to; false when it is not a plain field filter
// or that field is already taken.
function applyFieldFilter(node: AuditFilterNode, state: AuditFilterState): boolean {
    const tool = toolSelection(node);
    if (tool !== null && state.tool.values.length === 0) {
        state.tool = tool;
        return true;
    }
    if (!isLeaf(node)) {
        return false;
    }

    const { field, op, value } = node;
    const values = Array.isArray(value) ? value.map(String) : [];
    const text = typeof value === 'string' ? value : '';
    const isList = op === 'in' || op === 'not_in';

    if (field === 'kind' && op === 'in' && state.kinds.length === 0 && isOptionList(values, KIND_OPTIONS)) {
        state.kinds = values as AuditEventKind[];
        return true;
    }
    if (field === 'status' && op === 'in' && state.statuses.length === 0 && isOptionList(values, STATUS_OPTIONS)) {
        state.statuses = values as AuditEventStatus[];
        return true;
    }
    if (
        field === 'node_type' &&
        op === 'in' &&
        state.nodeTypes.length === 0 &&
        isOptionList(values, NODE_TYPE_OPTIONS)
    ) {
        state.nodeTypes = values as AuditNodeType[];
        return true;
    }
    if (field === 'flow_name' && isList && state.flow.values.length === 0) {
        state.flow = { op, values };
        return true;
    }
    if (field === 'agent' && isList && state.agent.values.length === 0 && values.every((id) => /^\d+$/.test(id))) {
        state.agent = { op, values };
        return true;
    }
    if (field === 'event_time' && op === 'gte' && state.dateFrom === null) {
        state.dateFrom = text;
        return true;
    }
    if (field === 'event_time' && op === 'lte' && state.dateTo === null) {
        state.dateTo = text;
        return true;
    }
    if (field === 'session_id') {
        return applySessionId(op, text, values, state);
    }
    // a tokens op the Tokens filter does not offer falls through to a Details condition on the same path
    const isTokensUnset = state.tokens.op !== 'is_empty' && state.tokens.value === '';
    if (field === TOKENS_FIELD && isTokensUnset && op === 'key_not_exists') {
        state.tokens = { op: 'is_empty', value: '' };
        return true;
    }
    if (field === TOKENS_FIELD && isTokensUnset && op !== 'is_empty' && TOKEN_OPERATORS.includes(op)) {
        state.tokens = { op, value: text };
        return true;
    }
    return false;
}

function applySessionId(op: AuditFilterOp, text: string, values: string[], state: AuditFilterState): boolean {
    const id = state.id;
    const isUnset = id.from === '' && id.to === '' && id.value === '' && id.values.length === 0;
    if (op === 'gte' || op === 'lte') {
        const bound = op === 'gte' ? 'from' : 'to';
        if (!isUnset && (id.mode !== 'range' || id[bound] !== '')) {
            return false;
        }
        state.id = { ...id, mode: 'range', [bound]: text };
        return true;
    }
    if (!isUnset) {
        return false;
    }
    if (op === 'in') {
        state.id = { ...id, mode: 'in', values };
        return true;
    }
    if (op === 'equals' || op === 'gt' || op === 'lt') {
        state.id = { ...id, mode: op, value: text };
        return true;
    }
    return false;
}

function conditionRoot(field: string): string | null {
    const root = field.split('.')[0];
    const spec = CONDITION_FIELDS.get(root);
    return spec !== undefined && (field === root || spec.hasKey) ? root : null;
}

// the single condition field every leaf of this and/or tree belongs to
function conditionRootOf(node: AuditFilterNode): string | null {
    if (isLeaf(node)) {
        return conditionRoot(node.field);
    }
    if (node.op === 'not') {
        return null;
    }
    const roots = new Set(node.children.map(conditionRootOf));
    const [root] = roots;
    return roots.size === 1 ? root : null;
}

function toCondition(leaf: AuditFilterNode, root: string, join: AuditConditionJoin): AuditCondition | null {
    const spec = CONDITION_FIELDS.get(root);
    if (!isLeaf(leaf) || spec === undefined || !spec.operators.includes(leaf.op)) {
        return null;
    }
    const value = VALUE_FREE_OPS.includes(leaf.op) ? '' : leaf.value;
    if (typeof value !== 'string') {
        return null;
    }
    const key = leaf.field === root ? '' : leaf.field.slice(root.length + 1);
    return { ...createAuditCondition(), join, key, op: leaf.op, value };
}

// A leaf is one group; an OR becomes groups joined by OR, where leaves extend the current
// group with OR and each AND of leaves opens a new group.
function conjunctGroups(node: AuditFilterNode, root: string): AuditConditionGroup[] | null {
    const children = isLeaf(node) ? [node] : node.op === 'or' ? node.children : [];
    const groups: AuditConditionGroup[] = [];
    for (const child of children) {
        const current = groups.at(-1);
        if (isLeaf(child) && current !== undefined) {
            const condition = toCondition(child, root, 'or');
            if (condition === null) {
                return null;
            }
            current.conditions.push(condition);
            continue;
        }
        const leaves = isLeaf(child) ? [child] : child.op === 'and' ? child.children : [];
        const conditions = leaves.map((leaf) => toCondition(leaf, root, 'and'));
        if (conditions.length === 0 || conditions.some((condition) => condition === null)) {
            return null;
        }
        groups.push({ ...createAuditConditionGroup(), conditions: conditions as AuditCondition[] });
    }
    return groups.length > 0 ? groups : null;
}

function conditionGroups(conjuncts: AuditFilterNode[], root: string): AuditConditionGroup[] | null {
    const perConjunct = conjuncts.map((node) => conjunctGroups(node, root));
    if (perConjunct.some((groups) => groups === null)) {
        return null;
    }
    // groups fold left, so a conjunct that needs several OR-joined groups only keeps its meaning first
    const ordered = (perConjunct as AuditConditionGroup[][]).sort((left, right) => right.length - left.length);
    return ordered.flatMap((groups, index) =>
        groups.map((group, groupIndex) => (index > 0 && groupIndex === 0 ? { ...group, join: 'and' } : group))
    );
}

function buildState(root: AuditFilterNode, base: AuditFilterState): AuditFilterState | null {
    const state = { ...base };
    const conditionConjuncts = new Map<string, AuditFilterNode[]>();

    for (const node of conjunctsOf(root)) {
        // Free text stays out of the Builder: the search box is a separate control.
        if (isLeaf(node) && node.field === FREE_TEXT_FIELD) {
            return null;
        }
        if (applyFieldFilter(node, state)) {
            continue;
        }
        const conditionRoot = conditionRootOf(node);
        if (conditionRoot === null) {
            return null;
        }
        conditionConjuncts.set(conditionRoot, [...(conditionConjuncts.get(conditionRoot) ?? []), node]);
    }

    for (const [conditionRoot, conjuncts] of conditionConjuncts) {
        const groups = conditionGroups(conjuncts, conditionRoot);
        const spec = CONDITION_FIELDS.get(conditionRoot);
        if (groups === null || spec === undefined) {
            return null;
        }
        state[spec.stateKey] = groups;
    }
    return state;
}

function isAllowedCombination(state: AuditFilterState): boolean {
    return Object.entries(AUDIT_FILTER_FIELDS).every(
        ([field, meta]) => !meta.isActive(state) || isFieldAvailable(field, state)
    );
}

// Builder state for the query, or null when the query does not parse or the Builder cannot show
// it with exactly the same meaning.
export function queryToBuilderState(query: string, current: AuditFilterState): AuditFilterState | null {
    const base: AuditFilterState = {
        ...EMPTY_AUDIT_FILTER,
        query: current.query,
        searchText: current.searchText,
        matchScope: current.matchScope,
    };
    if (query.trim() === '') {
        return base;
    }

    let parsed: AuditFilterNode;
    try {
        parsed = canonical(parseAuditQuery(query));
    } catch (error) {
        if (error instanceof AuditQueryParseError) {
            return null;
        }
        throw error;
    }

    const state = buildState(parsed, base);
    if (state === null || !isAllowedCombination(state)) {
        return null;
    }
    // safety net: the Builder must compile back to the very filter the text describes
    const compiled = compileAuditFilter({ ...state, searchText: '' }).filters;
    return compiled !== undefined && sameConjuncts(parsed, canonical(compiled)) ? state : null;
}
