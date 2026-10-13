import {
    AuditCondition,
    AuditConditionGroup,
    AuditConditionJoin,
    AuditEnumOption,
    AuditFilterState,
    AuditIdFilter,
    AuditIdMode,
    AuditMatchScopeState,
    AuditNumberFilter,
    createAuditConditionGroup,
    DEFAULT_MATCH_SCOPE,
    isUsableCondition,
} from '../models/audit-filter.models';
import {
    ID_MODE_OPTIONS,
    KIND_OPTIONS,
    NODE_TYPE_OPTIONS,
    OPERATOR_LABELS,
    STATUS_OPTIONS,
    TOKEN_OPERATOR_LABELS,
} from '../models/audit-filter-options';
import { formatAuditDay } from './format-audit-day.util';
import { highlightQuery } from './highlight-query.util';

export interface AuditFilterChipPart {
    text: string;
    isKeyword: boolean;
}

export interface AuditFilterChip {
    key: string;
    label: string;
    value: string;
    // set when the value has operators or joins worth highlighting; `value` is the same text, flattened
    parts?: AuditFilterChipPart[];
}

const plain = (text: string): AuditFilterChipPart => ({ text, isKeyword: false });
const keyword = (text: string): AuditFilterChipPart => ({ text, isKeyword: true });
const SPACE = plain(' ');

function parenthesize(parts: AuditFilterChipPart[]): AuditFilterChipPart[] {
    return [plain('('), ...parts, plain(')')];
}

function joinParts(
    left: AuditFilterChipPart[],
    join: AuditConditionJoin,
    right: AuditFilterChipPart[]
): AuditFilterChipPart[] {
    return [...left, SPACE, keyword(join.toUpperCase()), SPACE, ...right];
}

function createPartsChip(key: string, label: string, parts: AuditFilterChipPart[]): AuditFilterChip {
    return { key, label, value: parts.map((part) => part.text).join(''), parts };
}

function operatorChip(key: string, label: string, operator: string, values: string): AuditFilterChip {
    return createPartsChip(key, label, [keyword(operator), plain(` ${values}`)]);
}

function labelsFor(values: string[], options: AuditEnumOption[]): string {
    return values.map((value) => options.find((option) => option.value === value)?.label ?? value).join(', ');
}

function idModeLabel(mode: AuditIdMode): string {
    return ID_MODE_OPTIONS.find((option) => option.value === mode)?.label ?? mode;
}

function describeId(id: AuditIdFilter): string | null {
    if (id.mode === 'range') {
        if (id.from !== '' && id.to !== '') {
            return `${id.from} — ${id.to}`;
        }
        if (id.from !== '') {
            return `from ${id.from}`;
        }
        if (id.to !== '') {
            return `until ${id.to}`;
        }
        return null;
    }

    if (id.mode === 'in') {
        return id.values.length > 0 ? id.values.join(', ') : null;
    }

    if (id.value === '') {
        return null;
    }

    return id.mode === 'equals' ? id.value : `${idModeLabel(id.mode)} ${id.value}`;
}

function describeCondition(condition: AuditCondition): AuditFilterChipPart[] {
    const operator = keyword(OPERATOR_LABELS[condition.op] ?? condition.op);
    const key = condition.key === '' ? [] : [plain(condition.key), SPACE];
    const value = condition.value === '' ? [] : [SPACE, plain(condition.value)];
    return [...key, operator, ...value];
}

function describeConditions(conditions: AuditCondition[]): AuditFilterChipPart[] | null {
    const usable = conditions.filter(isUsableCondition);

    if (usable.length === 0) {
        return null;
    }

    let parts = describeCondition(usable[0]);
    for (let index = 1; index < usable.length; index++) {
        parts = joinParts(parts, usable[index].join, describeCondition(usable[index]));
    }

    return parts;
}

function describeConditionGroups(groups: AuditConditionGroup[]): AuditFilterChipPart[] | null {
    const described: { join: AuditConditionJoin; parts: AuditFilterChipPart[]; isCompound: boolean }[] = [];
    for (const group of groups) {
        const parts = describeConditions(group.conditions);
        if (parts !== null) {
            described.push({
                join: group.join,
                parts,
                isCompound: group.conditions.filter(isUsableCondition).length > 1,
            });
        }
    }
    if (described.length <= 1) {
        return described[0]?.parts ?? null;
    }

    return described.reduce<AuditFilterChipPart[]>((combined, part, index) => {
        const parts = part.isCompound ? parenthesize(part.parts) : part.parts;
        if (index === 0) {
            return parts;
        }
        const left = index > 1 ? parenthesize(combined) : combined;
        return joinParts(left, part.join, parts);
    }, []);
}

function conditionChip(key: string, label: string, groups: AuditConditionGroup[]): AuditFilterChip | null {
    const parts = describeConditionGroups(groups);
    return parts === null ? null : createPartsChip(key, label, parts);
}

function describeDate(from: string | null, to: string | null): string | null {
    if (from && to) {
        return `${formatAuditDay(from)} - ${formatAuditDay(to)}`;
    }
    if (from) {
        return `from ${formatAuditDay(from)}`;
    }
    if (to) {
        return `until ${formatAuditDay(to)}`;
    }
    return null;
}

function describeTokens(tokens: AuditNumberFilter): AuditFilterChip | null {
    if (tokens.op === 'is_empty') {
        return createPartsChip('tokens', 'Tokens', [keyword('is empty')]);
    }
    if (tokens.value === '') {
        return null;
    }
    const operator = TOKEN_OPERATOR_LABELS[tokens.op] ?? OPERATOR_LABELS[tokens.op] ?? tokens.op;
    return operatorChip('tokens', 'Tokens', operator, tokens.value);
}

function describeMatchScope(scope: AuditMatchScopeState): string | null {
    if (scope.fullSessionHistory) {
        return 'Whole session';
    }
    const parts = [
        scope.children ? 'Everything inside' : '',
        scope.rowsBeforeEnabled ? `${scope.rowsBefore} row(s) before` : '',
    ].filter((part) => part !== '');
    return parts.length > 0 ? parts.join(', ') : null;
}

export interface AuditFilterVocabularies {
    agents?: AuditEnumOption[];
    tools?: AuditEnumOption[];
}

export function describeAuditFilter(
    state: AuditFilterState,
    vocabularies: AuditFilterVocabularies = {}
): AuditFilterChip[] {
    const chips: AuditFilterChip[] = [];

    const matchScopeValue = describeMatchScope(state.matchScope);
    if (matchScopeValue !== null) {
        chips.push({ key: 'matchScope', label: 'Match scope', value: matchScopeValue });
    }

    const searchText = state.searchText.trim();
    if (searchText !== '') {
        chips.push({ key: 'search', label: 'Search', value: searchText });
    }

    if (state.mode === 'query') {
        const query = state.query.trim();
        if (query !== '') {
            chips.push(createPartsChip('query', 'Query', highlightQuery(query)));
        }
        return chips;
    }

    if (state.kinds.length > 0) {
        chips.push({ key: 'kind', label: 'Kind', value: labelsFor(state.kinds, KIND_OPTIONS) });
    }

    if (state.flow.values.length > 0) {
        chips.push(operatorChip('flow', 'Flow', OPERATOR_LABELS[state.flow.op], state.flow.values.join(', ')));
    }

    const idValue = describeId(state.id);
    if (idValue !== null) {
        chips.push({ key: 'id', label: 'ID', value: idValue });
    }

    if (state.statuses.length > 0) {
        chips.push({ key: 'status', label: 'Status', value: labelsFor(state.statuses, STATUS_OPTIONS) });
    }

    if (state.nodeTypes.length > 0) {
        chips.push({ key: 'nodeType', label: 'Node Type', value: labelsFor(state.nodeTypes, NODE_TYPE_OPTIONS) });
    }

    if (state.agent.values.length > 0) {
        const agents = labelsFor(state.agent.values, vocabularies.agents ?? []);
        chips.push(operatorChip('agent', 'Agent', OPERATOR_LABELS[state.agent.op], agents));
    }

    if (state.tool.values.length > 0) {
        const tools = labelsFor(state.tool.values, vocabularies.tools ?? []);
        chips.push(operatorChip('tool', 'Tool', OPERATOR_LABELS[state.tool.op], tools));
    }

    const leadingConditionChips = [
        conditionChip('input', 'Input', state.input),
        conditionChip('output', 'Output', state.output),
        conditionChip('error', 'Error', state.error),
        conditionChip('details', 'Details', state.details),
    ];
    chips.push(...leadingConditionChips.filter((chip) => chip !== null));

    const dateValue = describeDate(state.dateFrom, state.dateTo);
    if (dateValue !== null) {
        chips.push({ key: 'date', label: 'Date', value: dateValue });
    }

    const trailingChips = [
        conditionChip('task', 'Task', state.task),
        conditionChip('prompt', 'Prompt', state.prompt),
        conditionChip('messageText', 'Message text', state.messageText),
        describeTokens(state.tokens),
    ];
    chips.push(...trailingChips.filter((chip) => chip !== null));

    return chips;
}

export function clearAuditFilterField(state: AuditFilterState, key: string): AuditFilterState {
    switch (key) {
        case 'matchScope':
            return { ...state, matchScope: DEFAULT_MATCH_SCOPE };
        case 'kind':
            return { ...state, kinds: [] };
        case 'flow':
            return { ...state, flow: { op: 'in', values: [] } };
        case 'id':
            return { ...state, id: { mode: 'in', from: '', to: '', value: '', values: [] } };
        case 'status':
            return { ...state, statuses: [] };
        case 'nodeType':
            return { ...state, nodeTypes: [] };
        case 'input':
            return { ...state, input: [createAuditConditionGroup()] };
        case 'output':
            return { ...state, output: [createAuditConditionGroup()] };
        case 'error':
            return { ...state, error: [createAuditConditionGroup()] };
        case 'details':
            return { ...state, details: [createAuditConditionGroup()] };
        case 'date':
            return { ...state, dateFrom: null, dateTo: null };
        case 'agent':
            return { ...state, agent: { op: 'in', values: [] } };
        case 'tool':
            return { ...state, tool: { op: 'in', values: [] } };
        case 'task':
            return { ...state, task: [createAuditConditionGroup()] };
        case 'prompt':
            return { ...state, prompt: [createAuditConditionGroup()] };
        case 'messageText':
            return { ...state, messageText: [createAuditConditionGroup()] };
        case 'tokens':
            return { ...state, tokens: { op: 'gt', value: '' } };
        case 'query':
            return { ...state, mode: 'builder', query: '' };
        case 'search':
            return { ...state, searchText: '' };
        default:
            return state;
    }
}
