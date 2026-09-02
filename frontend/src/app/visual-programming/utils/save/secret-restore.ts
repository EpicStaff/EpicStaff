import { SecretDeclarationIndexService } from '@shared/services';

import { NodeType } from '../../core/enums/node-type';
import { FlowModel } from '../../core/models/flow.model';
import {
    ClassificationDecisionTableNodeModel,
    NodeModel,
    PythonNodeModel,
    WebhookTriggerNodeModel,
} from '../../core/models/node.model';

function restoreNodeSecretIds(
    node: NodeModel,
    graphId: number,
    index: Map<string, number[]>,
    service: SecretDeclarationIndexService
): NodeModel {
    if (service.readForbidden()) return node;

    switch (node.type) {
        case NodeType.PYTHON: {
            const pyNode = node as PythonNodeModel;
            if (pyNode.data.secret_ids) return node;
            const ids = service.lookup(index, graphId, node.node_name, NodeType.PYTHON, 'python_code');
            return { ...pyNode, data: { ...pyNode.data, secret_ids: ids } };
        }
        case NodeType.WEBHOOK_TRIGGER: {
            const whNode = node as WebhookTriggerNodeModel;
            if (whNode.data.python_code.secret_ids) return node;
            const ids = service.lookup(index, graphId, node.node_name, NodeType.WEBHOOK_TRIGGER, 'python_code');
            return {
                ...whNode,
                data: { ...whNode.data, python_code: { ...whNode.data.python_code, secret_ids: ids } },
            };
        }
        case NodeType.CLASSIFICATION_TABLE: {
            const cdtNode = node as ClassificationDecisionTableNodeModel;
            const table = cdtNode.data?.table;
            const preDefined = table?.pre_computation?.secret_ids !== undefined;
            const postDefined = table?.post_computation?.secret_ids !== undefined;
            if (preDefined && postDefined) return node;

            const preIds = preDefined
                ? undefined
                : service.lookup(index, graphId, node.node_name, NodeType.CLASSIFICATION_TABLE, 'pre_python_code');
            const postIds = postDefined
                ? undefined
                : service.lookup(index, graphId, node.node_name, NodeType.CLASSIFICATION_TABLE, 'post_python_code');

            return {
                ...cdtNode,
                data: {
                    ...cdtNode.data,
                    table: {
                        ...table,
                        pre_computation:
                            preIds !== undefined
                                ? { ...table?.pre_computation, secret_ids: preIds }
                                : table?.pre_computation,
                        post_computation:
                            postIds !== undefined
                                ? { ...table?.post_computation, secret_ids: postIds }
                                : table?.post_computation,
                    },
                },
            };
        }
        default:
            return node;
    }
}

export function restoreFlowSecretIds(
    flow: FlowModel,
    graphId: number,
    index: Map<string, number[]>,
    service: SecretDeclarationIndexService
): FlowModel {
    return { ...flow, nodes: flow.nodes.map((node) => restoreNodeSecretIds(node, graphId, index, service)) };
}

function mergeNodeSecretIds(node: NodeModel, savedByBackendId: Map<number, NodeModel>): NodeModel {
    if (node.backendId == null) return node;
    const saved = savedByBackendId.get(node.backendId);
    if (!saved || saved.type !== node.type) return node;

    switch (node.type) {
        case NodeType.PYTHON: {
            const savedIds = (saved as PythonNodeModel).data.secret_ids;
            if (!savedIds) return node;
            const pyNode = node as PythonNodeModel;
            return { ...pyNode, data: { ...pyNode.data, secret_ids: savedIds } };
        }
        case NodeType.WEBHOOK_TRIGGER: {
            const savedIds = (saved as WebhookTriggerNodeModel).data.python_code.secret_ids;
            if (!savedIds) return node;
            const whNode = node as WebhookTriggerNodeModel;
            return {
                ...whNode,
                data: { ...whNode.data, python_code: { ...whNode.data.python_code, secret_ids: savedIds } },
            };
        }
        case NodeType.CLASSIFICATION_TABLE: {
            const savedTable = (saved as ClassificationDecisionTableNodeModel).data?.table;
            const savedPre = savedTable?.pre_computation?.secret_ids;
            const savedPost = savedTable?.post_computation?.secret_ids;
            if (!savedPre && !savedPost) return node;

            const cdtNode = node as ClassificationDecisionTableNodeModel;
            const table = cdtNode.data?.table;
            return {
                ...cdtNode,
                data: {
                    ...cdtNode.data,
                    table: {
                        ...table,
                        pre_computation: savedPre
                            ? { ...table?.pre_computation, secret_ids: savedPre }
                            : table?.pre_computation,
                        post_computation: savedPost
                            ? { ...table?.post_computation, secret_ids: savedPost }
                            : table?.post_computation,
                    },
                },
            };
        }
        default:
            return node;
    }
}

export function mergeSecretIdsFromSaved(loaded: FlowModel, saved: FlowModel): FlowModel {
    const savedByBackendId = new Map<number, NodeModel>();
    for (const node of saved.nodes) {
        if (node.backendId != null) savedByBackendId.set(node.backendId, node);
    }
    return { ...loaded, nodes: loaded.nodes.map((node) => mergeNodeSecretIds(node, savedByBackendId)) };
}
