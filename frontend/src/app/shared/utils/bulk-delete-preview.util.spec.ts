import {
    BulkDeleteGroup,
    BulkDeleteResponse,
    BulkDeleteTarget,
    BulkDeleteUsageBucket,
    BulkDeleteUsageReport,
} from '@shared/models';
import { describe, expect, it } from 'vitest';

import { buildBulkDeletePreview } from './bulk-delete-preview.util';

const noopTarget: BulkDeleteTarget = {
    previewBulkDelete: () => {
        throw new Error('not used in this spec');
    },
    bulkDelete: () => {
        throw new Error('not used in this spec');
    },
    removeFromCache: () => {},
};

function group(items: { id: number; name: string }[], label = { singular: 'flow', plural: 'flows' }): BulkDeleteGroup {
    return { target: noopTarget, label, items };
}

function response(overrides: Partial<BulkDeleteResponse> = {}): BulkDeleteResponse {
    return {
        dry_run: true,
        deleted_count: 0,
        deleted_ids: [],
        deletable_ids: [],
        not_found_ids: [],
        skipped: [],
        usage: {},
        ...overrides,
    };
}

function bucket(overrides: Partial<BulkDeleteUsageBucket>): BulkDeleteUsageBucket {
    return {
        resource_type: 'flows',
        visible_count: 1,
        visible_sample: [],
        truncated: false,
        ...overrides,
    };
}

function usageReport(buckets: BulkDeleteUsageBucket[]): BulkDeleteUsageReport {
    return { blocked: false, by_resource_type: buckets };
}

describe('buildBulkDeletePreview', () => {
    it('splits items into deletable, blocked and not-found, preserving group.items order', () => {
        const items = [
            { id: 1, name: 'Alpha' },
            { id: 2, name: 'Beta' },
            { id: 3, name: 'Gamma' },
            { id: 4, name: 'Delta' },
        ];
        const res = response({
            deletable_ids: [1, 3],
            skipped: [{ id: 2, reason: 'in_use_restricted' }],
            not_found_ids: [4],
        });

        const preview = buildBulkDeletePreview(group(items), res);

        expect(preview.deletable.map((item) => item.id)).toEqual([1, 3]);
        expect(preview.blocked).toEqual([{ id: 2, name: 'Beta' }]);
        expect(preview.notFound).toEqual([{ id: 4, name: 'Delta' }]);
    });

    it('reads usage keyed by the id as a string', () => {
        const items = [{ id: 5, name: 'Alpha' }];
        const res = response({
            deletable_ids: [5],
            usage: {
                '5': usageReport([bucket({ resource_type: 'agents', visible_count: 2, visible_sample: [] })]),
            },
        });

        const preview = buildBulkDeletePreview(group(items), res);

        expect(preview.deletable[0].usage).toEqual([{ label: 'agents', count: 2, sampleNames: [], hasMore: true }]);
    });

    it('gives an item with no usage report an empty usage array', () => {
        const items = [{ id: 7, name: 'Alpha' }];
        const res = response({ deletable_ids: [7], usage: {} });

        const preview = buildBulkDeletePreview(group(items), res);

        expect(preview.deletable[0].usage).toEqual([]);
    });

    it('gives an item whose usage report has no buckets an empty usage array (e.g. a GraphVersion)', () => {
        const items = [{ id: 9, name: 'v1' }];
        const res = response({
            deletable_ids: [9],
            usage: { '9': usageReport([]) },
        });

        const preview = buildBulkDeletePreview(group(items), res);

        expect(preview.deletable[0].usage).toEqual([]);
    });

    it('omits buckets with visible_count 0', () => {
        const items = [{ id: 1, name: 'Alpha' }];
        const res = response({
            deletable_ids: [1],
            usage: {
                '1': usageReport([
                    bucket({ resource_type: 'agents', visible_count: 0, visible_sample: [] }),
                    bucket({
                        resource_type: 'projects',
                        visible_count: 1,
                        visible_sample: [{ resource_type: 'projects', kind: 'crew', id: 11, name: 'P1' }],
                    }),
                ]),
            },
        });

        const preview = buildBulkDeletePreview(group(items), res);

        expect(preview.deletable[0].usage).toEqual([
            { label: 'project', count: 1, sampleNames: ['P1'], hasMore: false },
        ]);
    });

    it('falls back to "#<id>" for a null sample name', () => {
        const items = [{ id: 1, name: 'Alpha' }];
        const res = response({
            deletable_ids: [1],
            usage: {
                '1': usageReport([
                    bucket({
                        resource_type: 'flows',
                        visible_count: 1,
                        visible_sample: [{ resource_type: 'flows', kind: 'flow', id: 42, name: null }],
                    }),
                ]),
            },
        });

        const preview = buildBulkDeletePreview(group(items), res);

        expect(preview.deletable[0].usage[0].sampleNames).toEqual(['#42']);
    });

    it('sets hasMore when truncated is true, even if the sample lists everything visible', () => {
        const items = [{ id: 1, name: 'Alpha' }];
        const res = response({
            deletable_ids: [1],
            usage: {
                '1': usageReport([
                    bucket({
                        resource_type: 'flows',
                        visible_count: 1,
                        visible_sample: [{ resource_type: 'flows', kind: 'flow', id: 1, name: 'F1' }],
                        truncated: true,
                    }),
                ]),
            },
        });

        const preview = buildBulkDeletePreview(group(items), res);

        expect(preview.deletable[0].usage[0].hasMore).toBe(true);
    });

    it('sets hasMore when the visible count exceeds the sample length, even if not truncated', () => {
        const items = [{ id: 1, name: 'Alpha' }];
        const res = response({
            deletable_ids: [1],
            usage: {
                '1': usageReport([
                    bucket({
                        resource_type: 'flows',
                        visible_count: 3,
                        visible_sample: [{ resource_type: 'flows', kind: 'flow', id: 1, name: 'F1' }],
                        truncated: false,
                    }),
                ]),
            },
        });

        const preview = buildBulkDeletePreview(group(items), res);

        expect(preview.deletable[0].usage[0].hasMore).toBe(true);
    });

    it('maps known resource types to a singular label when the bucket count is 1', () => {
        const items = [{ id: 1, name: 'Alpha' }];
        const res = response({
            deletable_ids: [1],
            usage: {
                '1': usageReport([
                    bucket({ resource_type: 'knowledge_sources', visible_count: 1, visible_sample: [] }),
                ]),
            },
        });

        const preview = buildBulkDeletePreview(group(items), res);

        expect(preview.deletable[0].usage[0].label).toBe('knowledge source');
    });

    it('maps known resource types to a plural label when the bucket count is more than 1', () => {
        const items = [{ id: 1, name: 'Alpha' }];
        const res = response({
            deletable_ids: [1],
            usage: {
                '1': usageReport([
                    bucket({ resource_type: 'knowledge_sources', visible_count: 4, visible_sample: [] }),
                ]),
            },
        });

        const preview = buildBulkDeletePreview(group(items), res);

        expect(preview.deletable[0].usage[0].label).toBe('knowledge sources');
    });

    it('falls back to the resource_type with underscores replaced by spaces for an unknown type', () => {
        const items = [{ id: 1, name: 'Alpha' }];
        const res = response({
            deletable_ids: [1],
            usage: {
                '1': usageReport([bucket({ resource_type: 'custom_widgets', visible_count: 2, visible_sample: [] })]),
            },
        });

        const preview = buildBulkDeletePreview(group(items), res);

        expect(preview.deletable[0].usage[0].label).toBe('custom widgets');
    });
});
