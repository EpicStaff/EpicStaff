/**
 * Elects one leader among the tabs of this browser that join the same name, and relays messages between them.
 *
 * The leader holds a Web Lock named after the group until it leaves or its tab closes; the other tabs queue for the
 * lock, so the next one is elected as soon as it is released. Messages go over a `BroadcastChannel` of the same name,
 * which reaches every other tab in the group and never the sender. A browser without either API makes every tab its
 * own leader, with nothing relayed. `navigator.locks` exists only in a secure context (HTTPS or localhost), so a
 * plain-HTTP deployment (SSL off, `http://<LAN IP>`) falls back to that too: one stream per tab.
 */
export class TabLeadership<TMessage> {
    private channel: BroadcastChannel | null = null;
    private pendingRequest: AbortController | null = null;
    private releaseLock: (() => void) | null = null;
    private leading = false;

    get isLeader(): boolean {
        return this.leading;
    }

    /** Leaves any previous group first. `onLead` may run synchronously, before `join` returns. */
    join(name: string, onLead: () => void, onMessage: (message: TMessage) => void): void {
        this.leave();
        if (typeof BroadcastChannel === 'undefined' || !('locks' in navigator)) {
            this.leading = true;
            onLead();
            return;
        }
        const channel = new BroadcastChannel(name);
        channel.onmessage = (event: MessageEvent<TMessage>) => onMessage(event.data);
        this.channel = channel;
        const pendingRequest = new AbortController();
        this.pendingRequest = pendingRequest;
        navigator.locks
            .request(name, { signal: pendingRequest.signal }, () => {
                // Granted after this tab left the group: returning releases the lock to the next tab at once.
                if (this.channel !== channel) return undefined;
                this.pendingRequest = null;
                this.leading = true;
                onLead();
                return new Promise<void>((resolve) => (this.releaseLock = resolve));
            })
            // An AbortError: the tab left the group while still queued.
            .catch(() => undefined);
    }

    /** To every other tab in the group. */
    post(message: TMessage): void {
        this.channel?.postMessage(message);
    }

    leave(): void {
        this.pendingRequest?.abort();
        this.pendingRequest = null;
        this.releaseLock?.();
        this.releaseLock = null;
        this.channel?.close();
        this.channel = null;
        this.leading = false;
    }
}
