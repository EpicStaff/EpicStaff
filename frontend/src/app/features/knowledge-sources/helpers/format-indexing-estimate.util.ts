import { formatCostUsd, formatTokens, toFiniteNumber } from '@shared/utils';

import { IndexingEstimate } from '../models/base-rag.model';

export const ALREADY_INDEXED_MESSAGE = 'Already indexed with these settings — re-running will not use any tokens.';

const APPROXIMATE_PREFIX = '≈ ';

/**
 * What the confirmation dialog shows for the estimate: `loading` while it is requested, `unavailable` when there is
 * none (failed, missing or malformed — indexing is never blocked), `already-indexed` when nothing will be embedded,
 * `ready` with the formatted tile values otherwise (`cost` is null when the price is unknown).
 */
export type IndexingEstimateView =
    | { state: 'loading' }
    | { state: 'unavailable' }
    | { state: 'already-indexed' }
    | { state: 'ready'; tokens: string; cost: string | null };

export function toIndexingEstimateView(estimate: IndexingEstimate | null): IndexingEstimateView {
    if (!estimate) return { state: 'unavailable' };
    if (estimate.document_count === 0) return { state: 'already-indexed' };

    const tokens = toFiniteNumber(estimate.embedding?.tokens);
    if (tokens === null) return { state: 'unavailable' };

    const prefix = estimate.embedding.exact ? '' : APPROXIMATE_PREFIX;
    return {
        state: 'ready',
        tokens: `${prefix}${formatTokens(tokens)}`,
        cost: formatEstimatedCost(estimate.embedding.cost_usd, prefix),
    };
}

function formatEstimatedCost(costUsd: unknown, prefix: string): string | null {
    const cost = toFiniteNumber(costUsd);
    if (cost === null) return null;
    const costText = formatCostUsd(cost);
    // "< $0.01" is already a bound; "≈ < $0.01" would say it twice.
    return costText.startsWith('<') ? costText : `${prefix}${costText}`;
}
