const MIN_VISIBLE_COST_USD = 0.01;
const TOKEN_FORMATTER = new Intl.NumberFormat('en-US');

export function toFiniteNumber(value: unknown): number | null {
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

const SMALL_COST_SIGNIFICANT_DIGITS = 2;
const MIN_SMALL_COST_USD = 0.000001;

/** Like `formatCostUsd`, but costs under a cent keep 2 significant digits (e.g. `$0.0012`); 0 or negative gives an empty string. */
export function formatSmallCostUsd(cost: number): string {
    if (!(cost > 0)) return '';
    if (cost >= MIN_VISIBLE_COST_USD) return formatCostUsd(cost);
    if (cost < MIN_SMALL_COST_USD) return '< $0.000001';
    const decimals = SMALL_COST_SIGNIFICANT_DIGITS - 1 - Math.floor(Math.log10(cost));
    return `$${cost.toFixed(decimals)}`;
}
