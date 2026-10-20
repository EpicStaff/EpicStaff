/**
 * Whether the flow save keeps a table's pre- or post-computation code block: it does while the block has code or
 * selected secrets, and otherwise drops it, libraries and execution timeout included. The panel always shows and
 * checks those fields and keeps their values on the node, so they are saved once the block gets code.
 */
export function isPythonCodeBlockSaved(
    code: string | null | undefined,
    secretIds: readonly number[] | null | undefined
): boolean {
    return !!code?.trim() || !!secretIds?.length;
}
