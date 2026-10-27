import { getIndexingUsageDetails, getIndexingUsageParts } from './format-indexing-usage.util';

describe('format-indexing-usage.util', () => {
    const NAIVE = { embedding_tokens: 12345, llm_input_tokens: null, llm_output_tokens: null, cost_usd: 0.42 };
    const GRAPH = { embedding_tokens: 12345, llm_input_tokens: 1200000, llm_output_tokens: 80000, cost_usd: 0.42 };
    const GRAPH_PARTS = ['12,345 embedding tokens', '1.2M LLM tokens in / 80K out'];

    it('returns no details for an empty object', () => {
        expect(getIndexingUsageDetails({})).toEqual([]);
    });

    it('omits the LLM part for naive usage', () => {
        expect(getIndexingUsageParts(NAIVE)).toEqual(['12,345 embedding tokens', '$0.42']);
    });

    it('shows compact LLM tokens for graph usage', () => {
        expect(getIndexingUsageParts(GRAPH)).toEqual([...GRAPH_PARTS, '$0.42']);
    });

    it('omits the LLM part when only one of input or output is set', () => {
        expect(getIndexingUsageParts({ ...GRAPH, llm_output_tokens: null })).toEqual([
            '12,345 embedding tokens',
            '$0.42',
        ]);
    });

    it('shows tokens only when the cost is unknown or not finite', () => {
        expect(getIndexingUsageParts({ ...GRAPH, cost_usd: null })).toEqual(GRAPH_PARTS);
        expect(getIndexingUsageParts({ ...NAIVE, cost_usd: Number.NaN })).toEqual(['12,345 embedding tokens']);
    });

    it('returns null for invalid embedding tokens', () => {
        expect(getIndexingUsageParts({ ...NAIVE, embedding_tokens: Number.NaN })).toBeNull();
    });

    it('builds last-run and total details, tolerating a missing section', () => {
        const lastRun = { ...GRAPH, completed_at: '2026-01-01T00:00:00Z' };
        expect(getIndexingUsageDetails({ last_run: lastRun, total: NAIVE })).toEqual([
            { label: 'Last indexing', parts: [...GRAPH_PARTS, '$0.42'] },
            { label: 'Total', parts: ['12,345 embedding tokens', '$0.42'] },
        ]);
        expect(getIndexingUsageDetails({ total: NAIVE })).toEqual([
            { label: 'Total', parts: ['12,345 embedding tokens', '$0.42'] },
        ]);
    });

    it('keeps a valid last run when the total is invalid', () => {
        const lastRun = { ...NAIVE, completed_at: '2026-01-01T00:00:00Z' };
        const invalidTotal = { ...NAIVE, embedding_tokens: Number.NaN };
        expect(getIndexingUsageDetails({ last_run: lastRun, total: invalidTotal })).toEqual([
            { label: 'Last indexing', parts: ['12,345 embedding tokens', '$0.42'] },
        ]);
    });
});
