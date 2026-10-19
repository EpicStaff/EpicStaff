import { formatCostUsd } from '@shared/utils';

import { IndexingEstimate } from '../models/base-rag.model';
import {
    ALREADY_INDEXED_MESSAGE,
    ESTIMATE_DISCLAIMER,
    formatEmbeddingEstimate,
    getIndexingEstimateHtml,
} from './format-indexing-estimate.util';

const NAIVE_ESTIMATE: IndexingEstimate = {
    rag_type: 'naive',
    document_count: 2,
    chunk_count: 40,
    embedding: { tokens: 12345, exact: false, cost_usd: 0.5 },
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
    });

    it('returns an empty string when there is no estimate', () => {
        expect(getIndexingEstimateHtml(null)).toBe('');
    });

    it('renders html for a naive estimate', () => {
        const html = getIndexingEstimateHtml(NAIVE_ESTIMATE);
        expect(html).toContain('class="dialog-callout"');
        expect(html).toContain('<div class="dialog-callout__title">Estimated usage</div>');
        expect(html).toContain('<div class="dialog-callout__line">Embedding: ≈ 12,345 tokens · ≈ $0.50</div>');
        expect(html).toContain(`<div class="dialog-callout__note">${ESTIMATE_DISCLAIMER}</div>`);
    });

    it('renders only the message line when there is nothing to index', () => {
        const html = getIndexingEstimateHtml({ ...NAIVE_ESTIMATE, document_count: 0 });
        expect(html).toContain(`<div class="dialog-callout__line">${ALREADY_INDEXED_MESSAGE}</div>`);
        expect(html).not.toContain('dialog-callout__title');
        expect(html).not.toContain('dialog-callout__note');
        expect(html).not.toContain(ESTIMATE_DISCLAIMER);
    });

    it('skips invalid values instead of throwing on a malformed estimate', () => {
        const malformed = {
            rag_type: 'naive',
            document_count: 1,
            chunk_count: 1,
            embedding: { tokens: 'abc', exact: true, cost_usd: 'x' },
        } as unknown as IndexingEstimate;
        expect(getIndexingEstimateHtml(malformed)).toBe('');
        expect(getIndexingEstimateHtml({ rag_type: 'naive', document_count: 1 } as unknown as IndexingEstimate)).toBe(
            ''
        );
    });
});
