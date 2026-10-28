import { EMPTY_TOOLS_FILTER, ToolsFilterState } from '../models/tool-filter.model';
import { buildPresetBody, restorePresetState, ToolPresetBody } from './tool-filter-preset-body.util';

describe('buildPresetBody', () => {
    it('maps frontend state keys to backend key names', () => {
        const state: ToolsFilterState = {
            ...EMPTY_TOOLS_FILTER,
            showFavoriteOnly: true,
            showNotFavoriteOnly: false,
            sortOrder: 'name_asc',
        };
        const body = buildPresetBody(state);
        expect(body).toEqual({
            showFavoriteOnly: true,
            showNotFavoriteOnly: false,
            sourceBuiltIn: false,
            sourceCustom: false,
            usageBuckets: [],
            unusedOnly: false,
            sortOrder: 'name_asc',
            includedToolIds: null,
            includedLabelIds: null,
            customConditions: EMPTY_TOOLS_FILTER.customConditions,
        } satisfies ToolPresetBody);
        expect(body).not.toBe(state);
    });
});

describe('restorePresetState', () => {
    it('restores from backend key names (primary path)', () => {
        const result = restorePresetState({ showFavoriteOnly: true, showNotFavoriteOnly: false });
        expect(result.showFavoriteOnly).toBe(true);
        expect(result.showNotFavoriteOnly).toBe(false);
        expect(result.sortOrder).toBe('default');
        expect(result.customConditions).toEqual(EMPTY_TOOLS_FILTER.customConditions);
    });

    it('restores from frontend key names (forward compat)', () => {
        const result = restorePresetState({ showFavoriteOnly: true });
        expect(result.showFavoriteOnly).toBe(true);
    });

    it('returns exact defaults for an empty body', () => {
        const result = restorePresetState({});
        expect(result).toEqual(EMPTY_TOOLS_FILTER);
    });

    it('round-trips through buildPresetBody', () => {
        const state: ToolsFilterState = {
            ...EMPTY_TOOLS_FILTER,
            showFavoriteOnly: true,
            sourceBuiltIn: true,
            sortOrder: 'name_asc',
            includedToolIds: [1, 2, 3],
        };
        const restored = restorePresetState(buildPresetBody(state));
        expect(restored).toEqual(state);
    });

    it('preserves all provided fields', () => {
        const body: Partial<ToolPresetBody> = {
            sourceBuiltIn: true,
            unusedOnly: true,
            includedToolIds: [1, 2, 3],
        };
        const result = restorePresetState(body);
        expect(result.sourceBuiltIn).toBe(true);
        expect(result.unusedOnly).toBe(true);
        expect(result.includedToolIds).toEqual([1, 2, 3]);
        expect(result.sourceCustom).toBe(false);
    });

    it('ignores unknown keys from the body', () => {
        const result = restorePresetState({ unknownKey: 'garbage', sortOrder: 'name_asc' });
        expect(result.sortOrder).toBe('name_asc');
        expect((result as unknown as Record<string, unknown>)['unknownKey']).toBeUndefined();
    });
});
