import { NodeType } from '@shared/models';

import { GetGraphLightRequest, GraphDto } from '../../../features/flows/models/graph.model';
import { FlowModel } from '../../core/models/flow.model';
import { createStartNode } from './create-start-node';
import { hasStartNode } from './has-start-node';
import { mapGraphDtoToFlowModel } from './map-graph-dto-to-flow-model';
import { normalizeFlowPorts } from './normalize-flow-ports';

/**
 * The single post-load pipeline that turns a persisted graph into the canvas model:
 * map DTO → add a Start node when missing → flag subgraph nodes whose target flow is gone
 * → fill / resync ports. Pure: no service access, so any canvas (live or preview) can use it.
 *
 * @param availableFlows flows the user can currently see; a subgraph node pointing at any
 *                       other id is marked `isBlocked`.
 */
export function buildFlowModelFromGraphDto(
    graph: GraphDto,
    availableFlows: readonly Pick<GetGraphLightRequest, 'id'>[]
): FlowModel {
    const mappedFlow = mapGraphDtoToFlowModel(graph);
    const flowWithStartNode = addStartNodeIfNeeded(mappedFlow);
    const validatedFlow = flagBlockedSubgraphNodes(flowWithStartNode, availableFlows);
    return normalizeFlowPorts(validatedFlow);
}

function addStartNodeIfNeeded(flowModel: FlowModel): FlowModel {
    if (hasStartNode(flowModel)) return flowModel;
    return { ...flowModel, nodes: [createStartNode(), ...flowModel.nodes] };
}

function flagBlockedSubgraphNodes(
    flowModel: FlowModel,
    availableFlows: readonly Pick<GetGraphLightRequest, 'id'>[]
): FlowModel {
    const availableIds = new Set(availableFlows.map((flow) => flow.id));
    return {
        ...flowModel,
        nodes: flowModel.nodes.map((node) => {
            if (node.type !== NodeType.SUBGRAPH) return node;
            const subgraphId = Number((node as { data?: { id?: unknown } })?.data?.id);
            const isMissing = !subgraphId || !availableIds.has(subgraphId);
            return { ...node, isBlocked: isMissing };
        }),
    };
}
