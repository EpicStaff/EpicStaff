/**
 * A code-only run executes what the backend stores for the node, not what the panel shows. These helpers let
 * a panel tell whether the two match and, when they do not, why its Run is blocked.
 */

/**
 * How a node's code relates to what the backend stores: `outdated` (another user saved the graph),
 * `not-created` (no backend id yet), `missing` (its backend id is not in the stored graph), `changed` (the
 * panel differs from the stored node in something the run uses) or `stored`.
 */
export type StoredCodeState = 'outdated' | 'not-created' | 'missing' | 'changed' | 'stored';

export const PYTHON_CODE_RUNNING_MESSAGE = 'The code is already running...';
export const SAVE_NODE_BEFORE_CODE_RUN_MESSAGE = 'Click Save to save the node before running the code';
export const SAVE_TO_RUN_LATEST_CODE_MESSAGE = 'Click Save to run your latest code changes';
/** A node with a backend id the stored graph no longer has (deleted, then restored by undo): only a graph save recreates it. */
export const SAVE_GRAPH_BEFORE_CODE_RUN_MESSAGE =
    'Click Save in the top panel to save the graph before running the code';
export const STORED_GRAPH_OUTDATED_MESSAGE = 'Another user saved this graph: refresh it to run the code';
export const NODE_SAVING_MESSAGE = 'The node is being saved...';

/**
 * The state of a node's code against `stored`, what the backend stores for it (null when the stored graph
 * does not have the node). `differsFromStored` compares the panel with it.
 */
export function resolveStoredCodeState<TStored>(
    hasSavedGraph: boolean,
    backendId: number | null,
    stored: TStored | null,
    differsFromStored: (stored: TStored) => boolean
): StoredCodeState {
    if (!hasSavedGraph) return 'outdated';
    if (backendId == null) return 'not-created';
    if (stored === null) return 'missing';
    return differsFromStored(stored) ? 'changed' : 'stored';
}

/**
 * What a code-only run executes, in a comparable form. The order of the secrets is not a difference, and
 * neither is surrounding whitespace of the code: the backend's PythonCodeSerializer stores `code` through a
 * DRF CharField (trim_whitespace), so it keeps code.strip() while the canvas keeps the code as typed.
 */
export function pythonCodeSignature(code: string, libraries: string[], secretIds: number[]): string {
    return JSON.stringify({
        code: code.trim(),
        libraries,
        secretIds: [...secretIds].sort((first, second) => first - second),
    });
}
