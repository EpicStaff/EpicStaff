import { evaluateCustomCondition, LabelDto } from '@shared/models';

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

export function compareFlowsByName(order: FlowSortOrder): (a: GetGraphLightRequest, b: GetGraphLightRequest) => number {
    if (order === 'name_asc') {
        return (a, b) => a.name.localeCompare(b.name, undefined, { sensitivity: 'base' });
    }
    if (order === 'name_desc') {
        return (a, b) => b.name.localeCompare(a.name, undefined, { sensitivity: 'base' });
    }
    return (a, b) => b.id - a.id;
}
