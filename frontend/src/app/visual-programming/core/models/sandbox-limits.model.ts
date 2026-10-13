/** `GET sandbox-limits/`: the limits the sandbox enforces on every code execution, the same for every user. */
export interface GetSandboxLimitsResponse {
    /** The longest execution timeout a node may set, in whole minutes (at least 1). */
    max_execution_timeout_minutes: number;
}
