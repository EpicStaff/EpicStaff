import { formatCostUsd } from '@shared/utils';

import { IndexingEstimate } from '../models/base-rag.model';
import {
    formatEmbeddingEstimate,
    formatLlmEstimate,
    getIndexingEstimateHtml,
    getIndexingEstimateLines,
} from './format-indexing-estimate.util';

const NAIVE_ESTIMATE: IndexingEstimate = {
    rag_type: 'naive',
    document_count: 2,
    chunk_count: 40,
    embedding: { tokens: 12345, exact: false, cost_usd: 0.5 },
    llm: null,
};

describe('format-indexing-estimate.util', () => {
    it('formats cost with a floor for sub-cent values', () => {
        expect(formatCostUsd(0.004)).toBe('< $0.01');
        expect(formatCostUsd(1.239)).toBe('$1.24');
        expect(formatCostUsd(0)).toBe('$0.00');
    });

    it('formats embedding with approximation prefix unless exact', () => {
        expect(formatEmbeddingEstimate(NAIVE_ESTIMATE.embedding)).toBe('≈ 12,345 tokens · ≈ $0.50');
        expect(formatEmbeddingEstimate({ tokens: 10, exact: true, cost_usd: 1 })).toBe('10 tokens · $1.00');
    });

    it('shows tokens only when cost is unknown', () => {
        expect(formatEmbeddingEstimate({ tokens: 1000, exact: false, cost_usd: null })).toBe('≈ 1,000 tokens');
        expect(
            formatLlmEstimate({ calls: 3, tokens_min: 1000, tokens_max: 2000, cost_usd_min: null, cost_usd_max: null })
        ).toBe('1,000–2,000 tokens');
    });

    it('shows a single cost when both ends of the llm range format the same', () => {
        expect(
            formatLlmEstimate({
                calls: 3,
                tokens_min: 1000,
                tokens_max: 2000,
                cost_usd_min: 0.001,
                cost_usd_max: 0.004,
            })
        ).toBe('1,000–2,000 tokens · < $0.01');
    });

    it('formats the llm range with costs', () => {
        expect(
            formatLlmEstimate({ calls: 3, tokens_min: 1000, tokens_max: 2000, cost_usd_min: 0.1, cost_usd_max: 0.3 })
        ).toBe('1,000–2,000 tokens · $0.10–$0.30');
    });

    it('adds a rough LLM line for graph estimates', () => {
        const lines = getIndexingEstimateLines({
            ...NAIVE_ESTIMATE,
            rag_type: 'graph',
            llm: { calls: 1, tokens_min: 1, tokens_max: 2, cost_usd_min: null, cost_usd_max: null },
        });
        expect(lines).toHaveLength(2);
        expect(lines[1]).toContain('rough estimate');
    });

    it('reports nothing to index when no documents will be indexed', () => {
        expect(getIndexingEstimateLines({ ...NAIVE_ESTIMATE, document_count: 0 })).toEqual(['Nothing new to index.']);
    });

    it('returns an empty string when there is no estimate', () => {
        expect(getIndexingEstimateHtml(null)).toBe('');
    });

    it('renders html for a naive estimate', () => {
        expect(getIndexingEstimateHtml(NAIVE_ESTIMATE)).toBe(
            '<div><strong>Estimated usage</strong><br>Embedding: ≈ 12,345 tokens · ≈ $0.50</div>'
        );
    });

    it('renders html for a graph estimate with cost min set and max null', () => {
        const html = getIndexingEstimateHtml({
            ...NAIVE_ESTIMATE,
            rag_type: 'graph',
            llm: { calls: 2, tokens_min: 1000, tokens_max: 3000, cost_usd_min: 0.1, cost_usd_max: null },
        });
        expect(html).toContain('Embedding: ≈ 12,345 tokens · ≈ $0.50');
        expect(html).toContain('LLM extraction (rough estimate): 1,000–3,000 tokens');
        expect(html).not.toContain('$0.10');
    });

    it('skips invalid values instead of throwing on a malformed estimate', () => {
        const malformed = {
            rag_type: 'graph',
            document_count: 1,
            chunk_count: 1,
            embedding: { tokens: 'abc', exact: true, cost_usd: 'x' },
            llm: { calls: 1, tokens_min: 5, tokens_max: undefined, cost_usd_min: null, cost_usd_max: null },
        } as unknown as IndexingEstimate;
        expect(getIndexingEstimateHtml(malformed)).toBe('');
        expect(getIndexingEstimateHtml({ rag_type: 'naive', document_count: 1 } as unknown as IndexingEstimate)).toBe(
            ''
        );
    });
});
