/** Tooltip on every per-config token price field (LLM create and edit dialogs). */
export const TOKEN_PRICE_HINT =
    "Leave empty to use the provider's published pricing. Set it for custom, self-hosted or gateway models whose price isn't known. Use a dot as the decimal separator.";

/** Tooltip on the per-config input token price field (LLM create and edit dialogs). */
export const INPUT_TOKEN_PRICE_HINT = `${TOKEN_PRICE_HINT} Cached prompt tokens, read or written, are counted at this price, so the session cost shown ignores the provider's cache rates.`;
