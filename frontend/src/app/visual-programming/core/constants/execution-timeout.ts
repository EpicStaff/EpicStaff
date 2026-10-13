import { NodeType } from '@shared/models';

/** The shortest execution timeout a node may set, in minutes. The longest comes from the sandbox limits. */
export const MIN_EXECUTION_TIMEOUT_MINUTES = 1;

/**
 * The default for a new node whose code is written by the user: a short limit stops runaway code (an endless
 * loop, a hanging request) early instead of holding a sandbox worker for the whole ceiling.
 */
export const USER_CODE_DEFAULT_EXECUTION_TIMEOUT_MINUTES = 3;

/** The node types that run code in the sandbox and carry an `execution_timeout`. */
export type ExecutionTimeoutNodeType =
    | NodeType.PYTHON
    | NodeType.WEBHOOK_TRIGGER
    | NodeType.CLASSIFICATION_TABLE
    | NodeType.FILE_EXTRACTOR
    | NodeType.AUDIO_TO_TEXT;

/**
 * Which default a new node gets: `user-code` nodes run code the user writes; `ceiling` nodes run built-in
 * code over user files, whose run time grows with the file size, so they get the longest timeout allowed.
 */
const DEFAULT_EXECUTION_TIMEOUT_KIND: Record<ExecutionTimeoutNodeType, 'user-code' | 'ceiling'> = {
    [NodeType.PYTHON]: 'user-code',
    [NodeType.WEBHOOK_TRIGGER]: 'user-code',
    [NodeType.CLASSIFICATION_TABLE]: 'user-code',
    [NodeType.FILE_EXTRACTOR]: 'ceiling',
    [NodeType.AUDIO_TO_TEXT]: 'ceiling',
};

export function isExecutionTimeoutNodeType(type: NodeType): type is ExecutionTimeoutNodeType {
    return type in DEFAULT_EXECUTION_TIMEOUT_KIND;
}

/** The execution timeout, in minutes, a new node of `type` starts with under the sandbox ceiling `maxMinutes`. */
export function defaultExecutionTimeoutMinutes(type: ExecutionTimeoutNodeType, maxMinutes: number): number {
    return DEFAULT_EXECUTION_TIMEOUT_KIND[type] === 'ceiling'
        ? maxMinutes
        : Math.min(USER_CODE_DEFAULT_EXECUTION_TIMEOUT_MINUTES, maxMinutes);
}
