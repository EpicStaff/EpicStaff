import {
    compareProviderCreationOrder,
    llmLibraryCardsPerRow,
    packLlmLibraryRows,
    providerCreationOrder,
} from './llm-library-layout.util';

describe('llmLibraryCardsPerRow', () => {
    it.each([
        [null, 4],
        [2000, 4],
        [1320, 4],
        [1319, 3],
        [652, 2],
        [651, 1],
        [200, 1],
    ])('fits %s px to %s cards a row', (width, expected) => {
        expect(llmLibraryCardsPerRow(width)).toBe(expected);
    });
});

describe('packLlmLibraryRows', () => {
    it.each([
        { sizes: [1, 2, 1], perRow: 4, rows: [[1, 2, 1]] },
        { sizes: [2, 3, 1], perRow: 4, rows: [[2], [3, 1]] },
        { sizes: [1, 6, 1], perRow: 4, rows: [[1], [6], [1]] },
        { sizes: [4, 4], perRow: 4, rows: [[4], [4]] },
        { sizes: [1, 1], perRow: 1, rows: [[1], [1]] },
        { sizes: [], perRow: 4, rows: [] },
    ])('packs groups of $sizes cards into $rows at $perRow a row', ({ sizes, perRow, rows }) => {
        expect(packLlmLibraryRows(sizes, (size) => size, perRow)).toEqual(rows);
    });
});

describe('compareProviderCreationOrder', () => {
    function sortedNames(providers: Record<string, { id: number; createdAt: string | null }[]>): string[] {
        return Object.keys(providers).sort((first, second) =>
            compareProviderCreationOrder(
                providerCreationOrder(providers[first]),
                providerCreationOrder(providers[second])
            )
        );
    }

    it('puts the provider whose earliest config was created first first', () => {
        expect(
            sortedNames({
                Ollama: [{ id: 2, createdAt: '2026-02-01T00:00:00Z' }],
                OpenAI: [
                    { id: 5, createdAt: '2026-03-01T00:00:00Z' },
                    { id: 9, createdAt: '2026-01-15T00:00:00Z' },
                ],
            })
        ).toEqual(['OpenAI', 'Ollama']);
    });

    it('puts a provider with no creation time after one with it, even with a lower config id', () => {
        expect(
            sortedNames({
                Anthropic: [{ id: 1, createdAt: null }],
                OpenAI: [{ id: 3, createdAt: '2026-01-01T00:00:00Z' }],
            })
        ).toEqual(['OpenAI', 'Anthropic']);
    });

    it('breaks a tie in creation time by the lowest config id', () => {
        expect(
            sortedNames({
                Ollama: [{ id: 8, createdAt: '2026-01-01T00:00:00Z' }],
                OpenAI: [{ id: 4, createdAt: '2026-01-01T00:00:00Z' }],
            })
        ).toEqual(['OpenAI', 'Ollama']);
    });

    // The old rule fell back to ids only for a pair missing a time, which made Gemini < Mistral < Cohere < Gemini
    // here: a cycle, so the result depended on the input order.
    it.each([
        ['Cohere', 'Gemini', 'Mistral'],
        ['Mistral', 'Cohere', 'Gemini'],
        ['Gemini', 'Mistral', 'Cohere'],
        ['Cohere', 'Mistral', 'Gemini'],
    ])('sorts a mix with and without creation times the same from any order (%s, %s, %s)', (...inputOrder) => {
        const providers: Record<string, { id: number; createdAt: string | null }[]> = {
            Cohere: [{ id: 2, createdAt: '2026-01-01T00:00:00Z' }],
            Gemini: [{ id: 5, createdAt: null }],
            Mistral: [{ id: 9, createdAt: '2025-06-01T00:00:00Z' }],
        };
        const ordered = Object.fromEntries(inputOrder.map((name) => [name, providers[name]]));

        expect(sortedNames(ordered)).toEqual(['Mistral', 'Cohere', 'Gemini']);
    });
});
