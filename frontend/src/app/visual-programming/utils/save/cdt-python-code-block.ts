/**
 * Whether the flow save keeps a table's pre- or post-computation code block: it does while the block has code or
 * selected secrets, and otherwise drops it, execution timeout included.
 */
export function isPythonCodeBlockSaved(
    code: string | null | undefined,
    secretIds: readonly number[] | null | undefined
): boolean {
    return !!code?.trim() || !!secretIds?.length;
}
