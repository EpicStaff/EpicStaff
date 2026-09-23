export enum GraphSessionStatus {
    RUNNING = 'run',
    ERROR = 'error',
    ENDED = 'end',
    WAITING_FOR_USER = 'wait_for_user',
    PENDING = 'pending',
    EXPIRED = 'expired',
    STOP = 'stop',
}

export const TERMINAL_SESSION_STATUSES: ReadonlySet<GraphSessionStatus> = new Set([
    GraphSessionStatus.ENDED,
    GraphSessionStatus.ERROR,
    GraphSessionStatus.STOP,
    GraphSessionStatus.EXPIRED,
]);

export const isTerminalSessionStatus = (status: GraphSessionStatus): boolean => TERMINAL_SESSION_STATUSES.has(status);
