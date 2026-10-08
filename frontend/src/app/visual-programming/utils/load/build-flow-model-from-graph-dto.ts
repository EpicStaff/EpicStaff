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
 * @param availableFlows optional flows to check subgraph targets against. A subgraph node with no
 *                       target id is always marked `isBlocked`; when this list is given, a node
 *                       pointing at any id outside it is marked `isBlocked` too. The live editor
 *                       omits it: the backend nulls the id once the target flow is deleted (hard or
 *                       soft) and rejects targets from another org, so the node's own id is the
 *                       source of truth, and a failed list load no longer blocks every subgraph
 *                       node. The version preview passes a list because snapshot ids are not
 *                       nulled when the target is deleted later.
 */
export function buildFlowModelFromGraphDto(
    graph: GraphDto,
    availableFlows?: readonly Pick<GetGraphLightRequest, 'id'>[]
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
    availableFlows?: readonly Pick<GetGraphLightRequest, 'id'>[]
): FlowModel {
    const availableIds = availableFlows ? new Set(availableFlows.map((flow) => flow.id)) : null;
    return {
        ...flowModel,
        nodes: flowModel.nodes.map((node) => {
            if (node.type !== NodeType.SUBGRAPH) return node;
            const subgraphId = Number((node as { data?: { id?: unknown } })?.data?.id);
            const isMissing = !subgraphId || (availableIds !== null && !availableIds.has(subgraphId));
            return { ...node, isBlocked: isMissing };
        }),
    };
}
