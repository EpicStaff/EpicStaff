import { FlowNodeListItem } from '@shared/components';
import {
    NodeType,
    SecretUsageCategoryDto,
    SecretUsageFlowItemDto,
    SecretUsageNamedItemDto,
    SecretUsageResourceType,
    SecretUsageResponse,
} from '@shared/models';
import { formatNodeLabel } from '@shared/utils';

export type SecretUsageCategoryIcon =
    | { kind: 'entity'; value: string }
    | { kind: 'tabler'; value: string }
    | { kind: 'svg'; value: string };

/** A node row of the flow node list: `name` is its label ("Name #N"), `key` its backend id so same-named rows stay apart. */
export interface SecretUsageFlowNode extends FlowNodeListItem {
    /** The node's backend id; the flow page opens the node by it (`?nodeId=`). */
    id: number;
    key: string;
}

export interface SecretUsageFlowItem {
    id: number;
    name: string;
    nodes: SecretUsageFlowNode[];
}

export interface SecretUsageResourceItem {
    name: string;
    type: SecretUsageResourceType;
}

export interface SecretUsageFlowCategory {
    key: 'flows';
    label: string;
    icon: SecretUsageCategoryIcon;
    items: SecretUsageFlowItem[];
}

export interface SecretUsageSimpleCategory {
    key: 'tools' | 'llm_configs';
    label: string;
    icon: SecretUsageCategoryIcon;
    items: SecretUsageResourceItem[];
}

export type SecretUsageCategory = SecretUsageFlowCategory | SecretUsageSimpleCategory;

export interface SecretUsageSummary {
    readableTotal: number;
    hiddenTotal: number;
    categories: SecretUsageCategory[];
}

const CATEGORY_DISPLAY: Record<SecretUsageCategoryDto['key'], { label: string; icon: SecretUsageCategoryIcon }> = {
    flows: { label: 'Flows', icon: { kind: 'svg', value: 'flows' } },
    tools: { label: 'Tools', icon: { kind: 'svg', value: 'tools' } },
    llm_configs: { label: 'LLM Configs', icon: { kind: 'tabler', value: 'ti ti-robot' } },
};

/**
 * A node with two PythonCode blocks (e.g. Classification Decision Table's pre/post computation)
 * reports one usage hit per code_field — dedupe those back into a single row per node so a secret
 * declared on both pre and post doesn't render (and count) as two separate nodes. Names aren't unique
 * in a flow, so the node's id tells hits apart.
 */
function dedupeFlowNodes(nodes: SecretUsageFlowItemDto['nodes']): SecretUsageFlowNode[] {
    const seen = new Set<number>();
    const result: SecretUsageFlowNode[] = [];
    for (const node of nodes) {
        if (seen.has(node.id)) continue;
        seen.add(node.id);
        result.push({
            id: node.id,
            key: String(node.id),
            name: formatNodeLabel({ node_name: node.name, nodeNumber: node.node_number }),
            nodeType: node.node_type as NodeType,
        });
    }
    return result;
}

export function toSecretUsageSummary(response: SecretUsageResponse): SecretUsageSummary {
    return {
        readableTotal: response.readable_total,
        hiddenTotal: response.hidden_total,
        categories: response.categories.map((category): SecretUsageCategory => {
            const { label, icon } = CATEGORY_DISPLAY[category.key];

            if (category.key === 'flows') {
                const items = category.items as SecretUsageFlowItemDto[];
                return {
                    key: 'flows',
                    label,
                    icon,
                    items: items.map((item) => ({
                        id: item.id,
                        name: item.name,
                        nodes: dedupeFlowNodes(item.nodes),
                    })),
                };
            }

            return {
                key: category.key,
                label,
                icon,
                items: category.items as SecretUsageNamedItemDto[],
            };
        }),
    };
}
