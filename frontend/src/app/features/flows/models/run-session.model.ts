export interface RunGraphResponse {
    session_id: number;
}

/** Trigger node types that support a test run with a hand-written payload. */
export type TestRunNodeType = 'webhook-trigger' | 'telegram-trigger';

/** Body of `POST run-session/test/` — starts a test run from a trigger node. */
export interface RunTestSessionRequest {
    graph_id: number;
    node_type: TestRunNodeType;
    node_id: number;
    payload: Record<string, unknown>;
}
