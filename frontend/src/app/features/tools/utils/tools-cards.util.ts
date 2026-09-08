import { evaluateCustomCondition } from '@shared/models';

import { GetBulkToolUsageItem } from '../models/tool-config.model';
import { ToolsFilterState, ToolSortOrder, UsageBucket } from '../models/tool-filter.model';
import { ToolCardVM } from '../pages/tools-list-page/components/tool-card/tool-card.model';

/**
 * Feature-shape adapter for the filter/sort helpers. Each tool kind (custom
 * python code tools, MCP tools) supplies its own accessors so the helpers stay
 * DTO-agnostic.
 */
export interface ToolFilterAdapter<T> {
    idOf: (t: T) => number;
    nameOf: (t: T) => string;
    labelIdsOf: (t: T) => number[];
    favoriteOf: (t: T) => boolean;
    /** Fields checked by the free-text search box (already trimmed strings). */
    searchableTextOf: (t: T) => string[];
    updatedAtOf: (t: T) => string | null | undefined;
    /** Optional "built-in" flag accessor. Only Custom-tab tools expose this;
     *  omit on adapters where the "Source" filter has no meaning (e.g. MCP). */
    builtInOf?: (t: T) => boolean;
}

export interface ToolFilterContext {
    filter: ToolsFilterState;
    sidebarLabelFilter: 'all' | 'unlabeled' | number;
    labelById: Map<number, { name: string; full_path: string }>;
    /** Pre-lowercased + trimmed search term (empty string when not searching). */
    searchTerm: string;
    /** Per-tool usage counts; consulted by the usage-bucket / unused-only filters and by usage-dependent sorts. */
    usage: Map<number, GetBulkToolUsageItem>;
    applySourceFilter: boolean;
}

const BUCKET_COUNT_KEY: Record<
    UsageBucket,
    keyof Pick<GetBulkToolUsageItem, 'agent_surface_count' | 'shared_surface_count' | 'inline_count'>
> = {
    agent_surface: 'agent_surface_count',
    shared_surface: 'shared_surface_count',
    inline: 'inline_count',
};

/**
 * Combined predicate: sidebar label filter, favorite, source (built-in vs
 * custom), usage buckets, unused-only, include/exclude sets, custom filter
 * condition, and free-text search.
 */
export function matchesToolFilter<T>(tool: T, ctx: ToolFilterContext, adapter: ToolFilterAdapter<T>): boolean {
    const { filter, sidebarLabelFilter, labelById, searchTerm, usage, applySourceFilter } = ctx;
    const labels = adapter.labelIdsOf(tool);
    const id = adapter.idOf(tool);

    // Sidebar single-label filter.
    if (sidebarLabelFilter === 'unlabeled' && labels.length > 0) return false;
    if (typeof sidebarLabelFilter === 'number' && !labels.includes(sidebarLabelFilter)) return false;

    // Favorite-only.
    if (filter.showFavoriteOnly && !adapter.favoriteOf(tool)) return false;

    if (applySourceFilter && adapter.builtInOf && filter.sourceBuiltIn !== filter.sourceCustom) {
        const isBuiltIn = adapter.builtInOf(tool);
        if (filter.sourceBuiltIn && !isBuiltIn) return false;
        if (filter.sourceCustom && isBuiltIn) return false;
    }

    if (usage.size > 0) {
        if (filter.unusedOnly) {
            const u = usage.get(id);
            const totalUsage = u ? u.agent_surface_count + u.shared_surface_count + u.inline_count : 0;
            if (totalUsage > 0) return false;
        } else if (filter.usageBuckets.length > 0) {
            const u = usage.get(id);
            const hitsAny = filter.usageBuckets.some((bucket) => (u?.[BUCKET_COUNT_KEY[bucket]] ?? 0) > 0);
            if (!hitsAny) return false;
        }
    }

    // Include/Exclude sets.
    if (filter.includedToolIds && !filter.includedToolIds.includes(id)) return false;
    if (filter.includedLabelIds) {
        const includeLabels = filter.includedLabelIds;
        if (!labels.some((lId) => includeLabels.includes(lId))) return false;
    }

    // Custom filter.
    if (filter.customFilter) {
        if (filter.customFilter.scope === 'tool_name') {
            if (!evaluateCustomCondition(adapter.nameOf(tool), filter.customFilter)) return false;
        } else {
            const names = labels.map((lId) => labelById.get(lId)?.name ?? '');
            if (!evaluateCustomCondition(names, filter.customFilter)) return false;
        }
    }

    // Free-text search: match the tool's own searchable text OR any assigned
    // label's name / full_path.
    if (searchTerm) {
        const haystack = adapter.searchableTextOf(tool);
        if (haystack.some((s) => s.toLowerCase().includes(searchTerm))) return true;
        const labelHit = labels.some((lId) => {
            const l = labelById.get(lId);
            return !!l && (l.name.toLowerCase().includes(searchTerm) || l.full_path.toLowerCase().includes(searchTerm));
        });
        if (!labelHit) return false;
    }
    return true;
}

/**
 * Comparator for the {@link ToolSortOrder} vocabulary. Falls back to newest-id
 * first for the `'default'` order (matches the previous per-component behaviour).
 */
export function compareTools<T>(
    a: T,
    b: T,
    sortOrder: ToolSortOrder,
    usage: Map<number, GetBulkToolUsageItem>,
    adapter: Pick<ToolFilterAdapter<T>, 'idOf' | 'nameOf' | 'updatedAtOf'>
): number {
    const usageSum = (id: number) => {
        const u = usage.get(id);
        return u ? u.agent_surface_count + u.shared_surface_count + u.inline_count : 0;
    };
    const idA = adapter.idOf(a);
    const idB = adapter.idOf(b);
    switch (sortOrder) {
        case 'last_modified': {
            const tsA = adapter.updatedAtOf(a);
            const tsB = adapter.updatedAtOf(b);
            const mA = tsA ? new Date(tsA).getTime() : -Infinity;
            const mB = tsB ? new Date(tsB).getTime() : -Infinity;
            return mB - mA;
        }
        case 'name_asc':
            return adapter.nameOf(a).localeCompare(adapter.nameOf(b));
        case 'name_desc':
            return adapter.nameOf(b).localeCompare(adapter.nameOf(a));
        case 'most_used':
            return usageSum(idB) - usageSum(idA);
        case 'unused_first':
            return usageSum(idA) - usageSum(idB);
        default:
            return idB - idA;
    }
}

/**
 * Projects a usage-count row onto the `ToolCardVM` usage fields. Zeros collapse
 * to `undefined` so the card template hides the corresponding chip, and
 * `unused` stays `false` when the "Show usage & unused" toggle is off (the
 * entry is treated as absent).
 */
export function toUsageVmFields(
    usage: Map<number, GetBulkToolUsageItem>,
    id: number,
    showUsage: boolean
): Pick<ToolCardVM, 'agentSurfaceUsage' | 'sharedSurfaceUsage' | 'inlineUsage' | 'unused'> {
    const u = showUsage ? usage.get(id) : undefined;
    return {
        agentSurfaceUsage: u?.agent_surface_count || undefined,
        sharedSurfaceUsage: u?.shared_surface_count || undefined,
        inlineUsage: u?.inline_count || undefined,
        unused: u?.agent_surface_count === 0 && u?.shared_surface_count === 0 && u?.inline_count === 0,
    };
}
