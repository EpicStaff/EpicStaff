import { computed, Injectable, signal } from '@angular/core';
import { NodeType } from '@shared/models';

import {
    FlowNodeReviewItem,
    FlowNodesByFile,
    mapBackendNodeType,
    ReviewItem,
    ReviewPythonCode,
    toFileNodeId,
} from '../../../../core/models/review-item.model';
import { CodeTab, FlowReviewNode, McpReviewableEntry, ReviewableEntry } from './model/review-entry.model';

interface CodeField {
    label: string | null;
    code: ReviewPythonCode;
}

interface ReviewedFileNode {
    item: FlowNodeReviewItem;
    fields: CodeField[];
}

/**
 * Identifies a node of an import file. Names may repeat within a flow, so a node is told apart by its
 * id in the file, which is unique per node type (each type is its own table). A file without ids
 * falls back to the name.
 */
function flowNodeKey(flowName: string, nodeType: string, nodeId: number | null, nodeName: string | null): string {
    const identity = nodeId === null ? `name:${nodeName ?? ''}` : `id:${nodeId}`;
    return `${flowName}::${nodeType}::${identity}`;
}

function toFlowReviewNode(key: string, name: string, backendNodeType: string, fields: CodeField[]): FlowReviewNode {
    return {
        key,
        name,
        nodeType: mapBackendNodeType(backendNodeType) ?? NodeType.PYTHON,
        codeFieldCount: fields.length,
        fieldKeys: fields.map((_, index) => `${key}::${index}`),
        codes: fields.map((field) => field.code),
        fieldLabels: fields.map((field) => field.label),
    };
}

@Injectable()
export class ReviewSessionStore {
    private pythonCodeToolCodes = new Map<string, ReviewPythonCode>();
    private mcpToolTransports = new Map<string, string>();
    private flowNodesByFlow = new Map<string, FlowReviewNode[]>();

    public readonly reviewedNodeKeys = signal<Set<string>>(new Set());
    private readonly viewedKeys = signal<Set<string>>(new Set());
    public reviewableEntries: ReviewableEntry[] = [];
    public readonly currentReviewIndex = signal(0);
    private readonly activeMcpEntry = signal<McpReviewableEntry | null>(null);
    public readonly currentReviewEntry = computed<ReviewableEntry | null>(
        () => this.activeMcpEntry() ?? this.reviewableEntries[this.currentReviewIndex()] ?? null
    );

    public readonly isReviewComplete = computed(() => {
        const reviewed = this.reviewedNodeKeys();
        return this.reviewableEntries.every((entry) => reviewed.has(entry.fieldKey));
    });

    public readonly unreviewedEntriesCount = computed(() => {
        const reviewed = this.reviewedNodeKeys();
        return this.reviewableEntries.filter((entry) => !reviewed.has(entry.fieldKey)).length;
    });

    public init(reviewItems: ReviewItem[], allFlowNodes: FlowNodesByFile): void {
        this.flowNodesByFlow = this.buildFlowNodesByKey(reviewItems, allFlowNodes);
        this.pythonCodeToolCodes = new Map(
            reviewItems
                .filter((item) => item.kind === 'python_code_tool')
                .map((item) => [item.name, item.python_code] as const)
        );
        this.mcpToolTransports = new Map(
            reviewItems.filter((item) => item.kind === 'mcp_tool').map((item) => [item.name, item.transport] as const)
        );
        this.reviewableEntries = this.buildReviewableEntries();
        this.markCurrentViewed();

        if (this.reviewableEntries.length > 0) {
            this.markReviewedKey(this.reviewableEntries[0].fieldKey);
        } else if (this.mcpToolTransports.size > 0) {
            const [firstMcpName] = this.mcpToolTransports.keys();
            this.goToToolCode(firstMcpName);
        }
    }

    private buildReviewableEntries(): ReviewableEntry[] {
        const entries: ReviewableEntry[] = [];
        for (const [name, code] of this.pythonCodeToolCodes) {
            entries.push({ kind: 'code', title: name, fieldKey: this.toolReviewKey(name), code, codeTabs: [] });
        }
        for (const nodes of this.flowNodesByFlow.values()) {
            for (const node of nodes) {
                const codeTabs: CodeTab[] = node.fieldLabels
                    .map((label, i) => (label ? { label, fieldKey: node.fieldKeys[i] } : null))
                    .filter((tab): tab is CodeTab => tab !== null);

                node.fieldKeys.forEach((fieldKey, i) => {
                    entries.push({ kind: 'code', title: node.name, fieldKey, code: node.codes[i], codeTabs });
                });
            }
        }
        return entries;
    }

    private buildFlowNodesByKey(
        reviewItems: ReviewItem[],
        allFlowNodes: FlowNodesByFile
    ): Map<string, FlowReviewNode[]> {
        const reviewedNodesByKey = new Map<string, ReviewedFileNode>();
        for (const item of reviewItems) {
            if (item.kind !== 'flow_node') continue;
            const fields: CodeField[] = [];
            if (item.python_code) fields.push({ label: null, code: item.python_code });
            if (item.pre_python_code) fields.push({ label: 'Pre-computation', code: item.pre_python_code });
            if (item.post_python_code) fields.push({ label: 'Post-computation', code: item.post_python_code });
            const key = flowNodeKey(item.flow_name, item.node_type, toFileNodeId(item.node_id), item.node_name);
            reviewedNodesByKey.set(key, { item, fields });
        }

        const map = new Map<string, FlowReviewNode[]>();
        for (const [flowName, nodes] of Object.entries(allFlowNodes)) {
            const list = nodes.map((node): FlowReviewNode => {
                const key = flowNodeKey(flowName, node.node_type, toFileNodeId(node.id), node.name);
                const fields = reviewedNodesByKey.get(key)?.fields ?? [];
                reviewedNodesByKey.delete(key);
                return toFlowReviewNode(key, node.name, node.node_type, fields);
            });
            map.set(flowName, list);
        }

        // Code the backend will import must never be hidden: a reviewed node the file list did not
        // match (a name or id it reads differently) still gets its own row.
        for (const [key, { item, fields }] of reviewedNodesByKey) {
            const row = toFlowReviewNode(key, item.node_name ?? 'Untitled node', item.node_type, fields);
            map.set(item.flow_name, [...(map.get(item.flow_name) ?? []), row]);
        }
        return map;
    }

    public goToCodeTab(fieldKey: string): void {
        this.activeMcpEntry.set(null);
        const index = this.reviewableEntries.findIndex((entry) => entry.fieldKey === fieldKey);
        if (index !== -1) {
            this.currentReviewIndex.set(index);
            this.markCurrentViewed();
        }
    }

    public onFlowNodeRowClick(node: FlowReviewNode): void {
        if (node.codeFieldCount === 0) return;
        this.goToCodeTab(node.fieldKeys[0]);
    }

    public goToPreviousReviewEntry(): void {
        const total = this.reviewableEntries.length;
        if (total === 0) return;
        this.activeMcpEntry.set(null);
        this.currentReviewIndex.update((i) => (i - 1 + total) % total);
        this.markCurrentViewed();
    }

    public goToNextReviewEntry(): void {
        const total = this.reviewableEntries.length;
        if (total === 0) return;
        const entry = this.currentReviewEntry();
        if (entry) this.markReviewedKey(entry.fieldKey);
        this.activeMcpEntry.set(null);
        this.currentReviewIndex.update((i) => (i + 1) % total);
        this.markCurrentViewed();
    }

    private markCurrentViewed(): void {
        const entry = this.currentReviewEntry();
        if (entry) this.markViewedKey(entry.fieldKey);
    }

    public isViewed(fieldKey: string): boolean {
        return this.viewedKeys().has(fieldKey);
    }

    private markViewedKey(fieldKey: string): void {
        if (this.viewedKeys().has(fieldKey)) return;
        this.viewedKeys.update((current) => new Set(current).add(fieldKey));
    }

    public flowNodes(flowName: string): FlowReviewNode[] {
        return this.flowNodesByFlow.get(flowName) ?? [];
    }

    public hasReviewNodes(flowName: string): boolean {
        return this.flowNodes(flowName).length > 0;
    }

    public isNodeReviewed(node: FlowReviewNode): boolean {
        return this.nodeReviewedFieldCount(node) === node.codeFieldCount;
    }

    public nodeReviewedFieldCount(node: FlowReviewNode): number {
        const reviewed = this.reviewedNodeKeys();
        return node.fieldKeys.filter((key) => reviewed.has(key)).length;
    }

    public nodeRemainingFieldCount(node: FlowReviewNode): number {
        return node.codeFieldCount - this.nodeReviewedFieldCount(node);
    }

    public isNodeBadgeClickable(node: FlowReviewNode): boolean {
        const reviewed = this.reviewedNodeKeys();
        const nextUnreviewed = node.fieldKeys.find((key) => !reviewed.has(key));
        if (!nextUnreviewed) return true;
        return this.isViewed(nextUnreviewed);
    }

    public toggleNodeReviewed(node: FlowReviewNode): void {
        const reviewed = this.reviewedNodeKeys();
        const nextUnreviewed = node.fieldKeys.find((key) => !reviewed.has(key));

        const next = new Set(reviewed);
        if (nextUnreviewed) {
            next.add(nextUnreviewed);
        } else {
            node.fieldKeys.forEach((key) => next.delete(key));
        }
        this.reviewedNodeKeys.set(next);
    }

    private toggleReviewedKey(key: string): void {
        const next = new Set(this.reviewedNodeKeys());
        if (next.has(key)) {
            next.delete(key);
        } else {
            next.add(key);
        }
        this.reviewedNodeKeys.set(next);
    }

    private markReviewedKey(key: string): void {
        if (this.reviewedNodeKeys().has(key)) return;
        this.reviewedNodeKeys.update((current) => new Set(current).add(key));
    }

    public hasPythonCode(name: string): boolean {
        return this.pythonCodeToolCodes.has(name);
    }

    public isMcpTool(name: string): boolean {
        return this.mcpToolTransports.has(name);
    }

    private toolReviewKey(name: string): string {
        return `tool::${name}`;
    }

    public isToolViewed(name: string): boolean {
        return this.isViewed(this.toolReviewKey(name));
    }

    public isToolReviewed(name: string): boolean {
        return this.reviewedNodeKeys().has(this.toolReviewKey(name));
    }

    public toggleToolReviewed(name: string): void {
        this.toggleReviewedKey(this.toolReviewKey(name));
    }

    public goToToolCode(name: string): void {
        const transport = this.mcpToolTransports.get(name);
        if (transport !== undefined) {
            this.activeMcpEntry.set({ kind: 'mcp', title: name, fieldKey: this.toolReviewKey(name), name, transport });
            this.markCurrentViewed();
            return;
        }
        this.goToCodeTab(this.toolReviewKey(name));
    }

    public flowReviewTotal(flowName: string): number {
        return this.flowNodes(flowName).reduce((sum, node) => sum + node.codeFieldCount, 0);
    }

    public flowReviewRemaining(flowName: string): number {
        return this.flowNodes(flowName).reduce((sum, node) => sum + this.nodeRemainingFieldCount(node), 0);
    }

    public isFlowFullyReviewed(flowName: string): boolean {
        return this.flowReviewRemaining(flowName) === 0;
    }
}
