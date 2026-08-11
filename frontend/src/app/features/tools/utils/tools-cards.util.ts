import { GetBulkToolUsageItem } from '../models/tool-config.model';
import { evaluateCustomCondition, ToolsFilterState, ToolSortOrder } from '../models/tool-filter.model';
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
}

export interface ToolFilterContext {
    filter: ToolsFilterState;
    sidebarLabelFilter: 'all' | 'unlabeled' | number;
    labelNameById: Map<number, string>;
    /** Pre-lowercased + trimmed search term (empty string when not searching). */
    searchTerm: string;
}

/**
 * Combined predicate: sidebar label filter, `showFavoriteOnly`, include/exclude
 * sets, custom filter condition, and free-text search — in the same order the
 * feature components previously applied them.
 */
export function matchesToolFilter<T>(tool: T, ctx: ToolFilterContext, adapter: ToolFilterAdapter<T>): boolean {
    const { filter, sidebarLabelFilter, labelNameById, searchTerm } = ctx;
    const labels = adapter.labelIdsOf(tool);

    // Sidebar single-label filter.
    if (sidebarLabelFilter === 'unlabeled' && labels.length > 0) return false;
    if (typeof sidebarLabelFilter === 'number' && !labels.includes(sidebarLabelFilter)) return false;

    // Favorite-only.
    if (filter.showFavoriteOnly && !adapter.favoriteOf(tool)) return false;

    // Include/Exclude sets.
    if (filter.includedToolIds && !filter.includedToolIds.includes(adapter.idOf(tool))) return false;
    if (filter.includedLabelIds) {
        const includeLabels = filter.includedLabelIds;
        if (!labels.some((id) => includeLabels.includes(id))) return false;
    }

    // Custom filter.
    if (filter.customFilter) {
        if (filter.customFilter.scope === 'tool_name') {
            if (!evaluateCustomCondition(adapter.nameOf(tool), filter.customFilter)) return false;
        } else {
            const names = labels.map((id) => labelNameById.get(id) ?? '');
            if (!names.some((n) => evaluateCustomCondition(n, filter.customFilter))) return false;
        }
    }

    // Free-text search.
    if (searchTerm) {
        const haystack = adapter.searchableTextOf(tool);
        if (!haystack.some((s) => s.toLowerCase().includes(searchTerm))) return false;
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
    adapter: Pick<ToolFilterAdapter<T>, 'idOf' | 'nameOf'>
): number {
    const usageSum = (id: number) => {
        const u = usage.get(id);
        return u ? u.projects_count + u.staff_count : 0;
    };
    const idA = adapter.idOf(a);
    const idB = adapter.idOf(b);
    switch (sortOrder) {
        case 'name_asc':
            return adapter.nameOf(a).localeCompare(adapter.nameOf(b));
        case 'name_desc':
            return adapter.nameOf(b).localeCompare(adapter.nameOf(a));
        case 'used_in_projects':
            return (usage.get(idB)?.projects_count ?? 0) - (usage.get(idA)?.projects_count ?? 0);
        case 'used_in_agents':
            return (usage.get(idB)?.staff_count ?? 0) - (usage.get(idA)?.staff_count ?? 0);
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
): Pick<ToolCardVM, 'projectsUsage' | 'agentsUsage' | 'unused'> {
    const u = showUsage ? usage.get(id) : undefined;
    return {
        projectsUsage: u?.projects_count || undefined,
        agentsUsage: u?.staff_count || undefined,
        unused: u?.projects_count === 0 && u?.staff_count === 0,
    };
}
