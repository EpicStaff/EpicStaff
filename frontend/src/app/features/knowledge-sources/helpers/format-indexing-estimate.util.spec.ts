import { IndexingEstimate } from '../models/base-rag.model';
import { IndexingEstimateView, toIndexingEstimateView } from './format-indexing-estimate.util';

function naiveEstimate(embedding: IndexingEstimate['embedding'], documentCount: number = 2): IndexingEstimate {
    return { rag_type: 'naive', document_count: documentCount, chunk_count: 40, embedding };
}

describe('toIndexingEstimateView', () => {
    it.each<[string, IndexingEstimate | null, IndexingEstimateView]>([
        [
            'an approximate estimate',
            naiveEstimate({ tokens: 3547, exact: false, cost_usd: 0.5 }),
            { state: 'ready', tokens: '≈ 3,547', cost: '≈ $0.50' },
        ],
        [
            'an exact estimate',
            naiveEstimate({ tokens: 10, exact: true, cost_usd: 1 }),
            { state: 'ready', tokens: '10', cost: '$1.00' },
        ],
        [
            'a sub-cent approximate cost, without a second bound',
            naiveEstimate({ tokens: 3547, exact: false, cost_usd: 0.004 }),
            { state: 'ready', tokens: '≈ 3,547', cost: '< $0.01' },
        ],
        [
            'an unknown cost',
            naiveEstimate({ tokens: 1000, exact: false, cost_usd: null }),
            { state: 'ready', tokens: '≈ 1,000', cost: null },
        ],
        ['no estimate', null, { state: 'unavailable' }],
        ['nothing to index', naiveEstimate({ tokens: 0, exact: true, cost_usd: 0 }, 0), { state: 'already-indexed' }],
    ])('maps %s', (_case, estimate, expected) => {
        expect(toIndexingEstimateView(estimate)).toEqual(expected);
    });

    it('treats a malformed estimate as unavailable instead of throwing', () => {
        const badTokens = { rag_type: 'naive', document_count: 1, embedding: { tokens: 'abc', exact: true } };
        const noEmbedding = { rag_type: 'naive', document_count: 1 };

        expect(toIndexingEstimateView(badTokens as unknown as IndexingEstimate)).toEqual({ state: 'unavailable' });
        expect(toIndexingEstimateView(noEmbedding as unknown as IndexingEstimate)).toEqual({ state: 'unavailable' });
    });

    it('drops a malformed cost but keeps the tokens', () => {
        const estimate = naiveEstimate({ tokens: 10, exact: true, cost_usd: 'x' as unknown as number });

        expect(toIndexingEstimateView(estimate)).toEqual({ state: 'ready', tokens: '10', cost: null });
    });
});
