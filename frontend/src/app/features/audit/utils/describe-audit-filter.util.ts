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
    RUN_TYPE_OPTIONS,
    STATUS_OPTIONS,
    TOKEN_OPERATOR_LABELS,
} from '../models/audit-filter-options';
import { formatAuditDay } from './format-audit-day.util';

export interface AuditFilterChip {
    key: string;
    label: string;
    value: string;
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

function describeCondition(condition: AuditCondition): string {
    const operator = OPERATOR_LABELS[condition.op] ?? condition.op;
    return [condition.key, operator, condition.value].filter((part) => part !== '').join(' ');
}

function describeConditions(conditions: AuditCondition[]): string | null {
    const usable = conditions.filter(isUsableCondition);

    if (usable.length === 0) {
        return null;
    }

    let text = describeCondition(usable[0]);
    for (let index = 1; index < usable.length; index++) {
        text += ` ${usable[index].join.toUpperCase()} ${describeCondition(usable[index])}`;
    }

    return text;
}

function describeConditionGroups(groups: AuditConditionGroup[]): string | null {
    const described: { join: AuditConditionJoin; text: string; isCompound: boolean }[] = [];
    for (const group of groups) {
        const text = describeConditions(group.conditions);
        if (text !== null) {
            described.push({
                join: group.join,
                text,
                isCompound: group.conditions.filter(isUsableCondition).length > 1,
            });
        }
    }
    if (described.length <= 1) {
        return described[0]?.text ?? null;
    }

    return described.reduce((combined, part, index) => {
        const text = part.isCompound ? `(${part.text})` : part.text;
        if (index === 0) {
            return text;
        }
        const left = index > 1 ? `(${combined})` : combined;
        return `${left} ${part.join.toUpperCase()} ${text}`;
    }, '');
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

function describeTokens(tokens: AuditNumberFilter): string | null {
    if (tokens.op === 'is_empty') {
        return 'is empty';
    }
    if (tokens.value === '') {
        return null;
    }
    const operator = TOKEN_OPERATOR_LABELS[tokens.op] ?? OPERATOR_LABELS[tokens.op] ?? tokens.op;
    return `${operator} ${tokens.value}`;
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
            chips.push({ key: 'query', label: 'Query', value: query });
        }
        return chips;
    }

    if (state.kinds.length > 0) {
        chips.push({ key: 'kind', label: 'Kind', value: labelsFor(state.kinds, KIND_OPTIONS) });
    }

    if (state.flow.values.length > 0) {
        chips.push({
            key: 'flow',
            label: 'Flow',
            value: `${OPERATOR_LABELS[state.flow.op]} ${state.flow.values.join(', ')}`,
        });
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

    if (state.runTypes.length > 0) {
        chips.push({ key: 'run', label: 'Run', value: labelsFor(state.runTypes, RUN_TYPE_OPTIONS) });
    }

    if (state.agent.values.length > 0) {
        chips.push({
            key: 'agent',
            label: 'Agent',
            value: `${OPERATOR_LABELS[state.agent.op]} ${labelsFor(state.agent.values, vocabularies.agents ?? [])}`,
        });
    }

    if (state.tool.values.length > 0) {
        chips.push({
            key: 'tool',
            label: 'Tool',
            value: `${OPERATOR_LABELS[state.tool.op]} ${labelsFor(state.tool.values, vocabularies.tools ?? [])}`,
        });
    }

    const inputText = describeConditionGroups(state.input);
    if (inputText !== null) {
        chips.push({ key: 'input', label: 'Input', value: inputText });
    }

    const outputText = describeConditionGroups(state.output);
    if (outputText !== null) {
        chips.push({ key: 'output', label: 'Output', value: outputText });
    }

    const errorText = describeConditionGroups(state.error);
    if (errorText !== null) {
        chips.push({ key: 'error', label: 'Error', value: errorText });
    }

    const detailsText = describeConditionGroups(state.details);
    if (detailsText !== null) {
        chips.push({ key: 'details', label: 'Details', value: detailsText });
    }

    const dateValue = describeDate(state.dateFrom, state.dateTo);
    if (dateValue !== null) {
        chips.push({ key: 'date', label: 'Date', value: dateValue });
    }
    const taskText = describeConditionGroups(state.task);
    if (taskText !== null) {
        chips.push({ key: 'task', label: 'Task', value: taskText });
    }

    const promptText = describeConditionGroups(state.prompt);
    if (promptText !== null) {
        chips.push({ key: 'prompt', label: 'Prompt', value: promptText });
    }

    const messageTextText = describeConditionGroups(state.messageText);
    if (messageTextText !== null) {
        chips.push({ key: 'messageText', label: 'Message text', value: messageTextText });
    }

    const tokensValue = describeTokens(state.tokens);
    if (tokensValue !== null) {
        chips.push({ key: 'tokens', label: 'Tokens', value: tokensValue });
    }

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
        case 'run':
            return { ...state, runTypes: [] };
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
