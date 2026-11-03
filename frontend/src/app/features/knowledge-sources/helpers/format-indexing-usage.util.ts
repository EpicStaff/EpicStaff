import { formatCostUsd, formatTokens, toFiniteNumber } from '@shared/utils';

import { IndexingUsage, IndexingUsageTotals } from '../models/base-rag.model';

const COMPACT_TOKEN_FORMATTER = new Intl.NumberFormat('en-US', { notation: 'compact', maximumFractionDigits: 1 });

function formatCompactTokens(tokens: number): string {
    return COMPACT_TOKEN_FORMATTER.format(Math.round(tokens));
}

/**
 * The parts of one usage line, e.g. ['12,345 embedding tokens', '1.2M LLM tokens in / 80K out', '$0.42'];
 * null when there is nothing valid to show. The view draws the separators between them.
 */
export function getIndexingUsageParts(totals: IndexingUsageTotals | undefined): string[] | null {
    const embedding = toFiniteNumber(totals?.embedding_tokens);
    if (!totals || embedding === null) return null;
    const parts = [`${formatTokens(embedding)} embedding tokens`];
    const llmInput = toFiniteNumber(totals.llm_input_tokens);
    const llmOutput = toFiniteNumber(totals.llm_output_tokens);
    if (llmInput !== null && llmOutput !== null) {
        parts.push(`${formatCompactTokens(llmInput)} LLM tokens in / ${formatCompactTokens(llmOutput)} out`);
    }
    const cost = toFiniteNumber(totals.cost_usd);
    if (cost !== null) parts.push(formatCostUsd(cost));
    return parts;
}

export interface IndexingUsageDetail {
    label: string;
    parts: string[];
}

/** Label/parts pairs ('Last indexing', 'Total') for the actual usage; empty for `{}` or invalid data. */
export function getIndexingUsageDetails(usage: IndexingUsage): IndexingUsageDetail[] {
    const details: IndexingUsageDetail[] = [];
    const last = getIndexingUsageParts(usage.last_run);
    if (last) details.push({ label: 'Last indexing', parts: last });
    const total = getIndexingUsageParts(usage.total);
    if (total) details.push({ label: 'Total', parts: total });
    return details;
}
