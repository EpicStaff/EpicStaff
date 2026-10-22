// Providers publish prices per million tokens; the API stores them per single token.
const TOKENS_PER_MILLION = 1_000_000;

// Rounding to significant digits (not fixed decimals) hides float noise such as 3.3000000000000003
// at any magnitude, so tiny per-token prices survive and a per-token → per-1M → per-token trip is lossless.
const SIGNIFICANT_DIGITS = 12;

function roundToSignificantDigits(value: number): number {
    return Number(value.toPrecision(SIGNIFICANT_DIGITS));
}

/** Converts a USD-per-1M-tokens price to USD per token. Empty (`null`/`undefined`) stays `null`, meaning default pricing. */
export function perMillionToPerToken(pricePerMillion: number | null | undefined): number | null {
    if (pricePerMillion === null || pricePerMillion === undefined) return null;
    return roundToSignificantDigits(pricePerMillion / TOKENS_PER_MILLION);
}

/** Converts a USD-per-token price to USD per 1M tokens, rounded for display. Empty (`null`/`undefined`) stays `null`. */
export function perTokenToPerMillion(pricePerToken: number | null | undefined): number | null {
    if (pricePerToken === null || pricePerToken === undefined) return null;
    return roundToSignificantDigits(pricePerToken * TOKENS_PER_MILLION);
}
