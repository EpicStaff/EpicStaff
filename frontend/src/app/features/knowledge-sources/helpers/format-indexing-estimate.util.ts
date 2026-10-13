import { IndexingEstimate } from '../models/base-rag.model';

const MIN_VISIBLE_COST_USD = 0.01;
const SAVED_SETTINGS_NOTE = 'Based on the last saved settings.';
const TOKEN_FORMATTER = new Intl.NumberFormat('en-US');

function toFiniteNumber(value: unknown): number | null {
    if (value === null || value === undefined) return null;
    const numeric = Number(value);
    return Number.isFinite(numeric) ? numeric : null;
}

export function formatTokens(tokens: number): string {
    return TOKEN_FORMATTER.format(Math.round(tokens));
}

export function formatCostUsd(cost: number): string {
    if (cost > 0 && cost < MIN_VISIBLE_COST_USD) return '< $0.01';
    return `$${cost.toFixed(2)}`;
}

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
    return `${tokensText} · ${formatCostUsd(costMin)}–${formatCostUsd(costMax)}`;
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
export function getIndexingEstimateHtml(estimate: IndexingEstimate | null, isBasedOnSavedSettings = false): string {
    if (!estimate) return '';
    try {
        const lines = getIndexingEstimateLines(estimate);
        if (!lines.length) return '';
        if (isBasedOnSavedSettings && estimate.document_count !== 0) lines.push(SAVED_SETTINGS_NOTE);
        return `<div><strong>Estimated usage</strong><br>${lines.join('<br>')}</div>`;
    } catch {
        return '';
    }
}
