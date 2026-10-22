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
