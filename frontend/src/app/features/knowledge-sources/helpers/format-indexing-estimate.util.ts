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

/** Plain-text lines (no markup) describing the estimate. Invalid values are skipped. */
function getIndexingEstimateLines(estimate: IndexingEstimate): string[] {
    const lines: string[] = [];
    const embeddingText = formatEmbeddingEstimate(estimate.embedding);
    if (embeddingText) lines.push(`Embedding: ${embeddingText}`);
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
