import { formatCostUsd, formatTokens, toFiniteNumber } from '@shared/utils';

import { IndexingEstimate } from '../models/base-rag.model';

export function formatEmbeddingEstimate(embedding: IndexingEstimate['embedding']): string | null {
    const tokens = toFiniteNumber(embedding?.tokens);
    if (tokens === null) return null;
    const prefix = embedding.exact ? '' : '≈ ';
    const tokensText = `${prefix}${formatTokens(tokens)} tokens`;
    const cost = toFiniteNumber(embedding.cost_usd);
    if (cost === null) return tokensText;
    return `${tokensText} · ${prefix}${formatCostUsd(cost)}`;
}

export function formatLlmEstimate(llm: NonNullable<IndexingEstimate['llm']>): string | null {
    const tokensMin = toFiniteNumber(llm?.tokens_min);
    const tokensMax = toFiniteNumber(llm?.tokens_max);
    if (tokensMin === null || tokensMax === null) return null;
    const tokensText = `${formatTokens(tokensMin)}–${formatTokens(tokensMax)} tokens`;
    const costMin = toFiniteNumber(llm.cost_usd_min);
    const costMax = toFiniteNumber(llm.cost_usd_max);
    if (costMin === null || costMax === null) return tokensText;
    const costMinText = formatCostUsd(costMin);
    const costMaxText = formatCostUsd(costMax);
    const costText = costMinText === costMaxText ? costMinText : `${costMinText}–${costMaxText}`;
    return `${tokensText} · ${costText}`;
}

/** Plain-text lines (no markup) describing the estimate; a single 'Nothing new to index.' line when no documents will be indexed. Invalid values are skipped. */
export function getIndexingEstimateLines(estimate: IndexingEstimate): string[] {
    if (estimate.document_count === 0) return ['Nothing new to index.'];

    const lines: string[] = [];
    const embeddingText = formatEmbeddingEstimate(estimate.embedding);
    if (embeddingText) lines.push(`Embedding: ${embeddingText}`);
    const llmText = estimate.llm ? formatLlmEstimate(estimate.llm) : null;
    if (llmText) lines.push(`LLM extraction (rough estimate): ${llmText}`);
    return lines;
}

/**
 * HTML for the confirmation dialog; every value is generated from numbers or constant text, so no user text is
 * interpolated. Never throws: a malformed estimate yields an empty string so indexing is not blocked.
 */
export function getIndexingEstimateHtml(estimate: IndexingEstimate | null): string {
    if (!estimate) return '';
    try {
        const lines = getIndexingEstimateLines(estimate);
        if (!lines.length) return '';
        return `<div><strong>Estimated usage</strong><br>${lines.join('<br>')}</div>`;
    } catch {
        return '';
    }
}
