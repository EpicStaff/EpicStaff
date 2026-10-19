import { escapeHtml, formatCostUsd, formatTokens, toFiniteNumber } from '@shared/utils';

import { IndexingEstimate } from '../models/base-rag.model';

export const ESTIMATE_DISCLAIMER = 'This is an estimate — the actual token usage and cost may differ.';
export const ALREADY_INDEXED_MESSAGE = 'Already indexed with these settings — re-running will not use any tokens.';

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

/** Plain-text lines (no markup) describing the estimate. Invalid values are skipped. */
export function getIndexingEstimateLines(estimate: IndexingEstimate): string[] {
    const lines: string[] = [];
    const embeddingText = formatEmbeddingEstimate(estimate.embedding);
    if (embeddingText) lines.push(`Embedding: ${embeddingText}`);
    const llmText = estimate.llm ? formatLlmEstimate(estimate.llm) : null;
    if (llmText) lines.push(`LLM extraction (rough estimate): ${llmText}`);
    return lines;
}

function renderLines(lines: string[]): string {
    return lines.map((line) => `<div class="dialog-callout__line">${escapeHtml(line)}</div>`).join('');
}

/**
 * HTML for the confirmation dialog callout. When no documents will be indexed it is just the "already indexed"
 * line; otherwise a titled estimate with a disclaimer. Never throws: a malformed estimate yields an empty string
 * so indexing is not blocked.
 */
export function getIndexingEstimateHtml(estimate: IndexingEstimate | null): string {
    if (!estimate) return '';
    try {
        if (estimate.document_count === 0) {
            return `<div class="dialog-callout">${renderLines([ALREADY_INDEXED_MESSAGE])}</div>`;
        }
        const lines = getIndexingEstimateLines(estimate);
        if (!lines.length) return '';
        return (
            '<div class="dialog-callout">' +
            '<div class="dialog-callout__title">Estimated usage</div>' +
            renderLines(lines) +
            `<div class="dialog-callout__note">${escapeHtml(ESTIMATE_DISCLAIMER)}</div>` +
            '</div>'
        );
    } catch {
        return '';
    }
}
