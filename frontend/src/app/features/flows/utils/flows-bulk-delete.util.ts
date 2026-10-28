import { BulkDeleteGroup, BulkDeleteLabel, BulkDeleteTarget } from '@shared/models';

export const FLOW_BULK_DELETE_LABEL: BulkDeleteLabel = { singular: 'flow', plural: 'flows' };

export function flowsBulkDeleteGroup(
    target: BulkDeleteTarget,
    flows: readonly { id: number; name: string }[],
    retentionDays: number | null
): BulkDeleteGroup {
    return {
        target,
        label: FLOW_BULK_DELETE_LABEL,
        items: flows.map((flow) => ({ id: flow.id, name: flow.name })),
        recycleBin: { retentionDays },
    };
}
