import { AuditFieldCatalog } from '../models/audit-domain.models';
import {
    AuditCondition,
    AuditConditionGroup,
    AuditFilterNode,
    AuditFilterState,
    AuditIdFilter,
    AuditMatchScopeState,
    catalogIdFilter,
    catalogSelection,
    catalogTextConditions,
    isUsableCondition,
    MAX_ROWS_BEFORE,
    VALUE_FREE_OPS,
} from '../models/audit-filter.models';
import { AuditMatchScope } from '../models/audit-session.models';

export const TOOL_NAME_FIELD = 'details.data.name';
export const TOKENS_FIELD = 'details.data.token_usage.total_tokens';

export interface AuditFilterQuery {
    filters?: AuditFilterNode;
    query?: string;
    // sessions only: no other domain nests its results
    matchScope?: AuditMatchScope;
}

// format and prepare condition payload for request (for error, input, output, details filters)
function compileConditions(root: string, conditions: AuditCondition[]): AuditFilterNode | null {
    const usable = conditions.filter(isUsableCondition);

    if (usable.length === 0) {
        return null;
    }

    const nodes: AuditFilterNode[] = usable.map((condition) => ({
        field: condition.key === '' ? root : `${root}.${condition.key}`,
        op: condition.op,
        value: VALUE_FREE_OPS.includes(condition.op) ? null : condition.value,
    }));

    let combined = nodes[0];
    for (let index = 1; index < nodes.length; index++) {
        combined = { op: usable[index].join, children: [combined, nodes[index]] };
    }
    return combined;
}

function compileConditionGroups(root: string, groups: AuditConditionGroup[]): AuditFilterNode | null {
    let combined: AuditFilterNode | null = null;
    for (const group of groups) {
        const node = compileConditions(root, group.conditions);
        if (node === null) {
            continue;
        }
        combined = combined === null ? node : { op: group.join, children: [combined, node] };
    }
    return combined;
}

function compileMatchScope(scope: AuditMatchScopeState): AuditMatchScope {
    if (scope.fullSessionHistory) {
        return { full_session_history: true };
    }
    return {
        ancestors: true,
        children: scope.children,
        // clamped here, not only in the input: a saved preset reaches this without passing through the UI
        rows_before: scope.rowsBeforeEnabled
            ? Math.min(Math.max(Math.trunc(scope.rowsBefore) || 1, 1), MAX_ROWS_BEFORE)
            : 0,
    };
}

function compileQuery(query: string, searchText: string): string {
    if (searchText === '') {
        return query;
    }
    const textClause = `text: "${searchText.replaceAll('"', '\\"')}"`;
    return query === '' ? textClause : `(${query}) and ${textClause}`;
}

function compileDateRange(state: AuditFilterState): AuditFilterNode[] {
    const leaves: AuditFilterNode[] = [];
    if (state.dateFrom) {
        leaves.push({ field: 'event_time', op: 'gte', value: state.dateFrom });
    }
    if (state.dateTo) {
        leaves.push({ field: 'event_time', op: 'lte', value: state.dateTo });
    }
    return leaves;
}

function compileIdFilter(field: string, id: AuditIdFilter): AuditFilterNode[] {
    const leaves: AuditFilterNode[] = [];
    if (id.mode === 'range') {
        if (id.from !== '') {
            leaves.push({ field, op: 'gte', value: Number(id.from) });
        }
        if (id.to !== '') {
            leaves.push({ field, op: 'lte', value: Number(id.to) });
        }
    } else if (id.mode === 'in') {
        if (id.values.length > 0) {
            leaves.push({ field, op: 'in', value: id.values.map(Number) });
        }
    } else if (id.value !== '') {
        leaves.push({ field, op: id.mode, value: Number(id.value) });
    }
    return leaves;
}

function compileSessionFilters(state: AuditFilterState): AuditFilterNode[] {
    const leaves: AuditFilterNode[] = [];

    if (state.kinds.length > 0) {
        leaves.push({ field: 'kind', op: 'in', value: state.kinds });
    }

    if (state.flow.values.length > 0) {
        leaves.push({ field: 'flow_name', op: state.flow.op, value: state.flow.values });
    }

    if (state.agent.values.length > 0) {
        leaves.push({ field: 'agent', op: state.agent.op, value: state.agent.values.map(Number) });
    }

    if (state.tool.values.length > 0) {
        const toolLeaves: AuditFilterNode[] = state.tool.values.map((value) => ({
            field: TOOL_NAME_FIELD,
            op: 'equals',
            value,
        }));
        const toolNode: AuditFilterNode = toolLeaves.length === 1 ? toolLeaves[0] : { op: 'or', children: toolLeaves };
        leaves.push(state.tool.op === 'not_in' ? { op: 'not', child: toolNode } : toolNode);
    }

    leaves.push(...compileIdFilter('session_id', state.id));

    if (state.statuses.length > 0) {
        leaves.push({ field: 'status', op: 'in', value: state.statuses });
    }

    leaves.push(...compileDateRange(state));

    if (state.nodeTypes.length > 0) {
        leaves.push({ field: 'node_type', op: 'in', value: state.nodeTypes });
    }

    const tokens = state.tokens;
    if (tokens.op === 'is_empty') {
        leaves.push({ field: TOKENS_FIELD, op: 'key_not_exists', value: null });
    } else if (tokens.value !== '') {
        leaves.push({ field: TOKENS_FIELD, op: tokens.op, value: Number(tokens.value) });
    }

    const errorNode = compileConditionGroups('error', state.error);
    if (errorNode !== null) {
        leaves.push(errorNode);
    }

    const inputNode = compileConditionGroups('input', state.input);
    if (inputNode !== null) {
        leaves.push(inputNode);
    }

    const outputNode = compileConditionGroups('output', state.output);
    if (outputNode !== null) {
        leaves.push(outputNode);
    }

    const detailsNode = compileConditionGroups('details', state.details);
    if (detailsNode !== null) {
        leaves.push(detailsNode);
    }

    const taskNode = compileConditionGroups('task', state.task);
    if (taskNode !== null) {
        leaves.push(taskNode);
    }

    const promptNode = compileConditionGroups('prompt', state.prompt);
    if (promptNode !== null) {
        leaves.push(promptNode);
    }

    const messageTextNode = compileConditionGroups('message_text', state.messageText);
    if (messageTextNode !== null) {
        leaves.push(messageTextNode);
    }

    return leaves;
}

function compileCatalogFilters(state: AuditFilterState, catalog: AuditFieldCatalog): AuditFilterNode[] {
    const leaves: AuditFilterNode[] = [];
    for (const builderField of catalog.builderFields) {
        if (builderField.kind === 'select') {
            const selection = catalogSelection(state, builderField.field);
            if (selection.values.length > 0) {
                leaves.push({ field: builderField.field, op: selection.op, value: selection.values });
            }
            continue;
        }
        if (builderField.kind === 'lookup') {
            const selection = catalogSelection(state, builderField.field);
            if (selection.values.length > 0) {
                leaves.push(builderField.compile(selection));
            }
            continue;
        }
        if (builderField.kind === 'id') {
            leaves.push(...compileIdFilter(builderField.field, catalogIdFilter(state, builderField.field)));
            continue;
        }
        const node = compileConditionGroups(builderField.field, catalogTextConditions(state, builderField));
        if (node !== null) {
            leaves.push(node);
        }
    }
    return [...leaves, ...compileDateRange(state)];
}

// `catalog` is the domain whose fields the state is read and compiled for; only sessions carry a match scope.
export function compileAuditFilter(state: AuditFilterState, catalog: AuditFieldCatalog): AuditFilterQuery {
    const isSessions = catalog.domain === 'sessions';
    const scope: Pick<AuditFilterQuery, 'matchScope'> = isSessions
        ? { matchScope: compileMatchScope(state.matchScope) }
        : {};
    const searchText = state.searchText.trim();

    if (state.mode === 'query') {
        const query = compileQuery(state.query.trim(), searchText);
        return query === '' ? scope : { query, ...scope };
    }

    const leaves: AuditFilterNode[] = [];
    if (searchText !== '') {
        leaves.push({ field: '__text__', op: 'contains', value: searchText });
    }
    leaves.push(...(isSessions ? compileSessionFilters(state) : compileCatalogFilters(state, catalog)));

    if (leaves.length === 0) {
        return scope;
    }

    return {
        filters: leaves.length === 1 ? leaves[0] : { op: 'and', children: leaves },
        ...scope,
    };
}
