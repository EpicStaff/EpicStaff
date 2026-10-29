import { EMPTY_TOOLS_FILTER, ToolsFilterState } from '../models/tool-filter.model';

/**
 * Shape accepted by the backend validator.
 * Maps frontend state keys to the backend-expected names.
 */
export interface ToolPresetBody {
    [key: string]: unknown;
    showFavoriteOnly: boolean;
    showNotFavoriteOnly: boolean;
    sourceBuiltIn: boolean;
    sourceCustom: boolean;
    usageBuckets: readonly string[];
    unusedOnly: boolean;
    sortOrder: string;
    includedToolIds: number[] | null;
    includedLabelIds: number[] | null;
    customConditions: unknown[] | null;
}

/** Snapshot the current filter state for persisting as a preset body. */
export function buildPresetBody(state: ToolsFilterState): ToolPresetBody {
    return {
        showFavoriteOnly: state.showFavoriteOnly,
        showNotFavoriteOnly: state.showNotFavoriteOnly,
        sourceBuiltIn: state.sourceBuiltIn,
        sourceCustom: state.sourceCustom,
        usageBuckets: [...state.usageBuckets],
        unusedOnly: state.unusedOnly,
        sortOrder: state.sortOrder,
        includedToolIds: state.includedToolIds,
        includedLabelIds: state.includedLabelIds,
        customConditions: state.customConditions,
    };
}

/** Merge a (possibly incomplete) saved body over defaults for forward compatibility. */
export function restorePresetState(body: Record<string, unknown>): ToolsFilterState {
    const mapped: Partial<ToolsFilterState> = {};

    // Backend key names → frontend key names
    if ('showFavoriteOnly' in body && typeof body['showFavoriteOnly'] === 'boolean')
        mapped.showFavoriteOnly = body['showFavoriteOnly'];
    if ('showNotFavoriteOnly' in body && typeof body['showNotFavoriteOnly'] === 'boolean')
        mapped.showNotFavoriteOnly = body['showNotFavoriteOnly'];
    // Forward compat with old presets that used the frontend key names
    if ('showFavoriteOnly' in body && typeof body['showFavoriteOnly'] === 'boolean')
        mapped.showFavoriteOnly = body['showFavoriteOnly'];
    if ('showNotFavoriteOnly' in body && typeof body['showNotFavoriteOnly'] === 'boolean')
        mapped.showNotFavoriteOnly = body['showNotFavoriteOnly'];

    if ('sourceBuiltIn' in body && typeof body['sourceBuiltIn'] === 'boolean')
        mapped.sourceBuiltIn = body['sourceBuiltIn'];
    if ('sourceCustom' in body && typeof body['sourceCustom'] === 'boolean') mapped.sourceCustom = body['sourceCustom'];
    if ('usageBuckets' in body && Array.isArray(body['usageBuckets']))
        mapped.usageBuckets = body['usageBuckets'] as ToolsFilterState['usageBuckets'];
    if ('unusedOnly' in body && typeof body['unusedOnly'] === 'boolean') mapped.unusedOnly = body['unusedOnly'];
    if ('sortOrder' in body && typeof body['sortOrder'] === 'string')
        mapped.sortOrder = body['sortOrder'] as ToolsFilterState['sortOrder'];
    if ('includedToolIds' in body && (Array.isArray(body['includedToolIds']) || body['includedToolIds'] === null))
        mapped.includedToolIds = body['includedToolIds'] as number[] | null;
    if ('includedLabelIds' in body && (Array.isArray(body['includedLabelIds']) || body['includedLabelIds'] === null))
        mapped.includedLabelIds = body['includedLabelIds'] as number[] | null;
    if ('customConditions' in body && (Array.isArray(body['customConditions']) || body['customConditions'] === null))
        mapped.customConditions = body['customConditions'] as ToolsFilterState['customConditions'];

    return { ...EMPTY_TOOLS_FILTER, ...mapped };
}
