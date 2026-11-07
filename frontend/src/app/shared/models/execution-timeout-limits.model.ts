/** `GET execution-timeout-limits/`: the bounds of a python code's execution timeout, in seconds, the same for every user. */
export interface GetExecutionTimeoutLimitsResponse {
    min_seconds: number;
    default_seconds: number;
    /** Null when there is no upper limit. */
    max_seconds: number | null;
}

export interface ExecutionTimeoutLimits {
    minSeconds: number;
    /** What the backend gives a python code saved without a timeout. */
    defaultSeconds: number;
    /** Null when there is no upper limit. The backend saves a longer timeout as this one. */
    maxSeconds: number | null;
}

/**
 * The timeout, in seconds, the backend keeps for a python code with `storedSeconds`: a code without one gets the
 * default, and a longer one is capped at the maximum, both on a save and on a restore or import. The minimum is not
 * applied: a save refuses a shorter timeout while an import raises it, so the two disagree below it.
 */
export function effectiveExecutionTimeoutSeconds(
    storedSeconds: number | null | undefined,
    { defaultSeconds, maxSeconds }: ExecutionTimeoutLimits
): number {
    const seconds = storedSeconds ?? defaultSeconds;
    return maxSeconds === null ? seconds : Math.min(seconds, maxSeconds);
}
