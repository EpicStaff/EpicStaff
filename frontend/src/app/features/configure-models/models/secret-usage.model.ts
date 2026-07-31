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
}

export interface SecretUsageFlowCategory {
    key: 'flows';
    label: string;
    icon: SecretUsageCategoryIcon;
    items: SecretUsageFlowItem[];
}

export interface SecretUsageSimpleCategory {
    key: 'tools' | 'llmConfigs' | 'ngrokConfig' | 'voiceTwilio';
    label: string;
    icon: SecretUsageCategoryIcon;
    items: SecretUsageResourceItem[];
}

export type SecretUsageCategory = SecretUsageFlowCategory | SecretUsageSimpleCategory;

export interface SecretUsageSummary {
    total: number;
    categories: SecretUsageCategory[];
}

// TODO: there's no backend endpoint yet for "which resources reference this secret" —
// both always report zero/empty until a real "secret usage" endpoint exists to call instead.
// eslint-disable-next-line @typescript-eslint/no-unused-vars
export function getSecretUsageCount(secretId: number): number {
    return 0;
}

// eslint-disable-next-line @typescript-eslint/no-unused-vars
export function getSecretUsage(secretId: number): SecretUsageSummary {
    return { total: 0, categories: [] };
}
