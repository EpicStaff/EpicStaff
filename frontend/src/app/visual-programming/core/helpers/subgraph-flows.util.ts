import { NodeType } from '@shared/models';

import { GetGraphLightRequest } from '../../../features/flows/models/graph.model';
import { CreateNodeRequest } from '../models/node-creation.types';

export function subgraphFlowOptions(
    flows: readonly GetGraphLightRequest[],
    currentFlowId: number | null
): GetGraphLightRequest[] {
    return flows.filter((flow) => flow.id !== currentFlowId);
}

export function subgraphNodeRequest(flow: GetGraphLightRequest): CreateNodeRequest {
    const lightData: GetGraphLightRequest = {
        id: flow.id,
        uuid: flow.uuid,
        name: flow.name,
        description: flow.description,
        tags: flow.tags || [],
    };
    return { type: NodeType.SUBGRAPH, overrides: { data: lightData as never } };
}
