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

    it('falls back to the lowest config id when a provider has no creation time', () => {
        expect(
            sortedNames({
                Anthropic: [{ id: 5, createdAt: null }],
                OpenAI: [{ id: 3, createdAt: '2026-01-01T00:00:00Z' }],
            })
        ).toEqual(['OpenAI', 'Anthropic']);
    });
});
