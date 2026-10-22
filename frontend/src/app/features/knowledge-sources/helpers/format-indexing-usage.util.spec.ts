import { formatIndexingUsageTotals, getIndexingUsageLines } from './format-indexing-usage.util';

describe('format-indexing-usage.util', () => {
    const SEP = ' · ';
    const NAIVE = { embedding_tokens: 12345, llm_input_tokens: null, llm_output_tokens: null, cost_usd: 0.42 };
    const GRAPH = { embedding_tokens: 12345, llm_input_tokens: 1200000, llm_output_tokens: 80000, cost_usd: 0.42 };
    const GRAPH_TEXT = `12,345 embedding tokens${SEP}1.2M LLM tokens in / 80K out`;

    it('returns no lines for an empty object', () => {
        expect(getIndexingUsageLines({})).toEqual([]);
    });

    it('omits the LLM part for naive usage', () => {
        expect(formatIndexingUsageTotals(NAIVE)).toBe(`12,345 embedding tokens${SEP}$0.42`);
    });

    it('shows compact LLM tokens for graph usage', () => {
        expect(formatIndexingUsageTotals(GRAPH)).toBe(`${GRAPH_TEXT}${SEP}$0.42`);
    });

    it('omits the LLM part when only one of input or output is set', () => {
        expect(formatIndexingUsageTotals({ ...GRAPH, llm_output_tokens: null })).toBe(
            `12,345 embedding tokens${SEP}$0.42`
        );
    });

    it('shows tokens only when the cost is unknown or not finite', () => {
        expect(formatIndexingUsageTotals({ ...GRAPH, cost_usd: null })).toBe(GRAPH_TEXT);
        expect(formatIndexingUsageTotals({ ...NAIVE, cost_usd: Number.NaN })).toBe('12,345 embedding tokens');
    });

    it('returns null for invalid embedding tokens', () => {
        expect(formatIndexingUsageTotals({ ...NAIVE, embedding_tokens: Number.NaN })).toBeNull();
    });

    it('builds last-run and total lines, tolerating a missing section', () => {
        const lastRun = { ...GRAPH, completed_at: '2026-01-01T00:00:00Z' };
        expect(getIndexingUsageLines({ last_run: lastRun, total: NAIVE })).toEqual([
            `Last indexing: ${GRAPH_TEXT}${SEP}$0.42`,
            `Total: 12,345 embedding tokens${SEP}$0.42`,
        ]);
        expect(getIndexingUsageLines({ total: NAIVE })).toEqual([`Total: 12,345 embedding tokens${SEP}$0.42`]);
    });

    it('keeps a valid last run when the total is invalid', () => {
        const lastRun = { ...NAIVE, completed_at: '2026-01-01T00:00:00Z' };
        const invalidTotal = { ...NAIVE, embedding_tokens: Number.NaN };
        expect(getIndexingUsageLines({ last_run: lastRun, total: invalidTotal })).toEqual([
            `Last indexing: 12,345 embedding tokens${SEP}$0.42`,
        ]);
    });
});
