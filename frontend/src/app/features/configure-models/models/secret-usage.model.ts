import {
    SecretUsageCategoryDto,
    SecretUsageFlowItemDto,
    SecretUsageNamedItemDto,
    SecretUsageResourceType,
    SecretUsageResponse,
} from '@shared/models';

import { NodeType } from '../../../visual-programming/core/enums/node-type';

export type SecretUsageCategoryIcon =
    | { kind: 'entity'; value: string }
    | { kind: 'tabler'; value: string }
    | { kind: 'svg'; value: string };

export interface SecretUsageFlowNode {
    name: string;
    nodeType: NodeType;
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
    total: number;
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
 * declared on both pre and post doesn't render (and count) as two separate nodes.
 */
function dedupeFlowNodes(nodes: SecretUsageFlowItemDto['nodes']): SecretUsageFlowNode[] {
    const seen = new Set<string>();
    const result: SecretUsageFlowNode[] = [];
    for (const node of nodes) {
        const key = `${node.name}:${node.node_type}`;
        if (seen.has(key)) continue;
        seen.add(key);
        result.push({ name: node.name, nodeType: node.node_type as NodeType });
    }
    return result;
}

export function toSecretUsageSummary(response: SecretUsageResponse): SecretUsageSummary {
    return {
        total: response.total,
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
