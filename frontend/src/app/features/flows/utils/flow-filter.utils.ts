import { evaluateCustomCondition, LabelDto } from '@shared/models';

import { isUsableCondition } from '../../audit/models/audit-filter.models';
import { AuditConditionGroup } from '../../audit/models/audit-filter.models';
import { CustomFilterCondition, FlowSortOrder } from '../models/flow-filter.model';
import { GetGraphLightRequest } from '../models/graph.model';

export function evaluateCustomFilter(
    condition: CustomFilterCondition,
    flow: GetGraphLightRequest,
    labels: LabelDto[]
): boolean {
    const haystacks =
        condition.scope === 'flow_name'
            ? [flow.name]
            : (flow.label_ids ?? []).map((id) => labels.find((l) => l.id === id)?.name).filter((n): n is string => !!n);

    return evaluateCustomCondition(haystacks, condition);
}

export function evaluateFlowConditionGroups(
    groups: AuditConditionGroup[],
    flow: GetGraphLightRequest,
    labels: LabelDto[]
): boolean {
    const hasActiveCondition = groups.some((group) => group.conditions.some((c) => isUsableCondition(c)));
    if (!hasActiveCondition) return true;

    const fieldMap: Record<string, string[]> = {
        flow_name: [flow.name],
        description: [flow.description ?? ''],
        label: (flow.label_ids ?? [])
            .map((id) => labels.find((l) => l.id === id))
            .filter(Boolean)
            .flatMap((l) => [l!.name, l!.full_path]),
    };

    // Groups are OR'd — at least one must match
    return groups.some((group) => {
        const active = group.conditions.filter((c) => isUsableCondition(c));
        if (active.length === 0) return true;

        let result = evaluateSingleFlowCondition(active[0], fieldMap);
        for (let i = 1; i < active.length; i++) {
            const conditionResult = evaluateSingleFlowCondition(active[i], fieldMap);
            if (active[i].join === 'and') {
                result = result && conditionResult;
            } else {
                result = result || conditionResult;
            }
        }
        return result;
    });
}

function evaluateSingleFlowCondition(
    condition: { key: string; op: string; value: string },
    fieldMap: Record<string, string[]>
): boolean {
    const texts = condition.key ? (fieldMap[condition.key] ?? []) : Object.values(fieldMap).flat();
    return texts.some((text) => matchesOperator(text, condition.op, condition.value));
}

function matchesOperator(text: string, op: string, value: string): boolean {
    const haystack = text.toLowerCase();
    const needle = value.trim().toLowerCase();
    switch (op) {
        case 'equals':
            return haystack === needle;
        case 'not_equal':
            return haystack !== needle;
        case 'contains':
            return haystack.includes(needle);
        case 'not_contains':
            return !haystack.includes(needle);
        case 'starts_with':
            return haystack.startsWith(needle);
        case 'ends_with':
            return haystack.endsWith(needle);
        case 'is_empty':
            return haystack.trim() === '';
        case 'is_not_empty':
            return haystack.trim() !== '';
        default:
            return true;
    }
}

export function compareFlows(order: FlowSortOrder): (a: GetGraphLightRequest, b: GetGraphLightRequest) => number {
    if (order === 'name_asc') {
        return (a, b) => a.name.localeCompare(b.name, undefined, { sensitivity: 'base' });
    }
    if (order === 'name_desc') {
        return (a, b) => b.name.localeCompare(a.name, undefined, { sensitivity: 'base' });
    }
    if (order === 'last_modified') {
        return (a, b) => {
            const aDate = a.updated_at ?? a.created_at ?? '';
            const bDate = b.updated_at ?? b.created_at ?? '';
            return bDate.localeCompare(aDate);
        };
    }
    return (a, b) => b.id - a.id;
}
