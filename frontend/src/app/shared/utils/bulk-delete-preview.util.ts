import {
    BulkDeleteGroup,
    BulkDeleteItem,
    BulkDeleteLabel,
    BulkDeletePreviewGroup,
    BulkDeletePreviewItem,
    BulkDeleteResponse,
    BulkDeleteUsageBucket,
    BulkDeleteUsageLine,
} from '@shared/models';

const KNOWN_USAGE_LABELS: Record<string, BulkDeleteLabel> = {
    flows: { singular: 'flow', plural: 'flows' },
    agents: { singular: 'agent', plural: 'agents' },
    knowledge_sources: { singular: 'knowledge source', plural: 'knowledge sources' },
};

/** Maps a raw dry-run `BulkDeleteResponse` onto the dialog's view model. */
export function buildBulkDeletePreview(group: BulkDeleteGroup, response: BulkDeleteResponse): BulkDeletePreviewGroup {
    const deletableIds = new Set(response.deletable_ids);
    const blockedIds = new Set(response.skipped.map((entry) => entry.id));
    const notFoundIds = new Set(response.not_found_ids);

    const deletable: BulkDeletePreviewItem[] = [];
    const blocked: BulkDeleteItem[] = [];
    const notFound: BulkDeleteItem[] = [];

    for (const item of group.items) {
        if (deletableIds.has(item.id)) {
            deletable.push({ id: item.id, name: item.name, usage: buildUsageLines(response, item.id) });
        } else if (blockedIds.has(item.id)) {
            blocked.push({ id: item.id, name: item.name });
        } else if (notFoundIds.has(item.id)) {
            notFound.push({ id: item.id, name: item.name });
        }
    }

    return { label: group.label, recycleBin: group.recycleBin, deletable, blocked, notFound };
}

function buildUsageLines(response: BulkDeleteResponse, id: number): BulkDeleteUsageLine[] {
    const report = response.usage[String(id)];
    if (!report) return [];

    return report.by_resource_type.filter((bucket) => bucket.visible_count > 0).map(buildUsageLine);
}

function buildUsageLine(bucket: BulkDeleteUsageBucket): BulkDeleteUsageLine {
    return {
        label: usageLabel(bucket.resource_type, bucket.visible_count),
        count: bucket.visible_count,
        sampleNames: bucket.visible_sample.map((ref) => ref.name ?? `#${ref.id}`),
        hasMore: bucket.truncated || bucket.visible_count > bucket.visible_sample.length,
    };
}

function usageLabel(resourceType: string, count: number): string {
    const label = KNOWN_USAGE_LABELS[resourceType];
    if (!label) return resourceType.replace(/_/g, ' ');
    return count === 1 ? label.singular : label.plural;
}
