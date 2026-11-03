import { BulkDeleteTarget } from '@shared/models';
import { describe, expect, it } from 'vitest';

import {
    llmLibraryBulkDeleteGroups,
    LlmLibraryBulkDeleteSource,
    LlmLibrarySelectionKind,
} from './llm-library-bulk-delete.util';

function noopTarget(): BulkDeleteTarget {
    return {
        previewBulkDelete: () => {
            throw new Error('not used in this spec');
        },
        bulkDelete: () => {
            throw new Error('not used in this spec');
        },
        removeFromCache: () => {},
    };
}

function buildSources(): Record<LlmLibrarySelectionKind, LlmLibraryBulkDeleteSource> {
    return {
        llm: {
            label: { singular: 'LLM config', plural: 'LLM configs' },
            target: noopTarget(),
            configs: [
                { id: 1, custom_name: 'GPT-4 config' },
                { id: 2, custom_name: 'GPT-3.5 config' },
            ],
        },
        embedding: {
            label: { singular: 'embedding config', plural: 'embedding configs' },
            target: noopTarget(),
            configs: [{ id: 10, custom_name: 'Ada embedding' }],
        },
        openai: {
            label: { singular: 'OpenAI voice config', plural: 'OpenAI voice configs' },
            target: noopTarget(),
            configs: [{ id: 20, custom_name: 'OpenAI voice A' }],
        },
        elevenlabs: {
            label: { singular: 'ElevenLabs voice config', plural: 'ElevenLabs voice configs' },
            target: noopTarget(),
            configs: [{ id: 30, custom_name: 'ElevenLabs voice A' }],
        },
        gemini: {
            label: { singular: 'Gemini voice config', plural: 'Gemini voice configs' },
            target: noopTarget(),
            configs: [{ id: 40, custom_name: 'Gemini voice A' }],
        },
    };
}

describe('llmLibraryBulkDeleteGroups', () => {
    it('parses a "kind:id" key and groups the id under its kind', () => {
        const sources = buildSources();

        const groups = llmLibraryBulkDeleteGroups(new Set(['llm:1']), sources);

        expect(groups).toEqual([
            { target: sources.llm.target, label: sources.llm.label, items: [{ id: 1, name: 'GPT-4 config' }] },
        ]);
    });

    it('produces one group per kind that has a selection', () => {
        const sources = buildSources();

        const groups = llmLibraryBulkDeleteGroups(new Set(['llm:1', 'embedding:10']), sources);

        expect(groups).toHaveLength(2);
        expect(groups.find((group) => group.label === sources.llm.label)?.items).toEqual([
            { id: 1, name: 'GPT-4 config' },
        ]);
        expect(groups.find((group) => group.label === sources.embedding.label)?.items).toEqual([
            { id: 10, name: 'Ada embedding' },
        ]);
    });

    it('collects multiple selected ids of the same kind into one group', () => {
        const sources = buildSources();

        const groups = llmLibraryBulkDeleteGroups(new Set(['llm:1', 'llm:2']), sources);

        expect(groups).toHaveLength(1);
        expect(groups[0].items).toEqual([
            { id: 1, name: 'GPT-4 config' },
            { id: 2, name: 'GPT-3.5 config' },
        ]);
    });

    it('skips kinds with no selection', () => {
        const sources = buildSources();

        const groups = llmLibraryBulkDeleteGroups(new Set(['llm:1']), sources);

        expect(groups.some((group) => group.label === sources.embedding.label)).toBe(false);
        expect(groups.some((group) => group.label === sources.openai.label)).toBe(false);
        expect(groups.some((group) => group.label === sources.elevenlabs.label)).toBe(false);
        expect(groups.some((group) => group.label === sources.gemini.label)).toBe(false);
    });

    it('skips ids that are no longer present in that kind storage', () => {
        const sources = buildSources();

        const groups = llmLibraryBulkDeleteGroups(new Set(['llm:1', 'llm:999']), sources);

        expect(groups[0].items).toEqual([{ id: 1, name: 'GPT-4 config' }]);
    });

    it('omits a kind entirely when every selected id for it is missing from storage', () => {
        const sources = buildSources();

        const groups = llmLibraryBulkDeleteGroups(new Set(['llm:999']), sources);

        expect(groups).toEqual([]);
    });

    it('uses each source label verbatim for its group, for every voice provider kind', () => {
        const sources = buildSources();

        const groups = llmLibraryBulkDeleteGroups(new Set(['openai:20', 'elevenlabs:30', 'gemini:40']), sources);

        expect(groups.find((group) => group.items[0]?.id === 20)?.label).toEqual(sources.openai.label);
        expect(groups.find((group) => group.items[0]?.id === 30)?.label).toEqual(sources.elevenlabs.label);
        expect(groups.find((group) => group.items[0]?.id === 40)?.label).toEqual(sources.gemini.label);
    });

    it('returns an empty array when nothing is selected', () => {
        const sources = buildSources();

        expect(llmLibraryBulkDeleteGroups(new Set(), sources)).toEqual([]);
    });
});
