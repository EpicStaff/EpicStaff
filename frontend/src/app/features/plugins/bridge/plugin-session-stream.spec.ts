import { Observable, of, throwError } from 'rxjs';

import { BridgeSessionMessageData, BridgeSessionStatusData, BridgeSubscriptionClosedData } from './bridge-protocol';
import { PluginSessionStream, PluginSessionStreamOptions, TERMINAL_GRACE_MS } from './plugin-session-stream';
import { FakeEventSource } from './testing/bridge-test-harness';

describe('PluginSessionStream', () => {
    let options: PluginSessionStreamOptions;
    let onMessage: ReturnType<typeof vi.fn<(data: BridgeSessionMessageData) => void>>;
    let onStatus: ReturnType<typeof vi.fn<(data: BridgeSessionStatusData) => void>>;
    let onClosed: ReturnType<typeof vi.fn<(data: BridgeSubscriptionClosedData) => void>>;
    let fetchTicket: ReturnType<typeof vi.fn<() => Observable<string>>>;

    beforeEach(() => {
        vi.useFakeTimers();
        FakeEventSource.instances.length = 0;
        onMessage = vi.fn<(data: BridgeSessionMessageData) => void>();
        onStatus = vi.fn<(data: BridgeSessionStatusData) => void>();
        onClosed = vi.fn<(data: BridgeSubscriptionClosedData) => void>();
        fetchTicket = vi.fn<() => Observable<string>>(() => of('ticket'));
        options = {
            sessionId: 9,
            fetchTicket,
            streamUrl: (sessionId, ticket) => `/stream/${sessionId}?ticket=${ticket}`,
            createEventSource: (url) => new FakeEventSource(url) as unknown as EventSource,
            onMessage,
            onStatus,
            onClosed,
        };
    });

    afterEach(() => vi.useRealTimers());

    function latestSource(): FakeEventSource {
        const source = FakeEventSource.instances.at(-1);
        if (!source) throw new Error('no EventSource was opened');
        return source;
    }

    it('relays messages once each, keyed by uuid, and only for its own session', () => {
        new PluginSessionStream(options).start();
        const message = {
            session_id: 9,
            uuid: 'u1',
            name: 'Answer',
            created_at: 't',
            message_data: { message_type: 'llm' },
        };

        latestSource().emit('messages', message);
        latestSource().emit('messages', message);
        latestSource().emit('messages', { ...message, uuid: 'u2', session_id: 10 });

        expect(onMessage).toHaveBeenCalledTimes(1);
        expect(onMessage).toHaveBeenCalledWith({
            message_type: 'llm',
            name: 'Answer',
            created_at: 't',
            message_data: { message_type: 'llm' },
        });
    });

    it('reconnects with a fresh ticket after an error, then gives up with reason "error"', () => {
        new PluginSessionStream(options).start();

        for (let attempt = 0; attempt < 3; attempt++) {
            latestSource().fail();
            vi.runOnlyPendingTimers();
        }
        expect(fetchTicket).toHaveBeenCalledTimes(4);

        latestSource().fail();
        expect(onClosed).toHaveBeenCalledWith({ reason: 'error' });
        expect(latestSource().closed).toBe(true);
    });

    it('gives up when no ticket can be fetched', () => {
        fetchTicket.mockImplementation(() => throwError(() => new Error('no ticket')));
        new PluginSessionStream(options).start();

        vi.runAllTimers();

        expect(onClosed).toHaveBeenCalledWith({ reason: 'error' });
        expect(FakeEventSource.instances).toEqual([]);
    });

    it('keeps relaying for the grace period after a final status, then closes with "ended"', () => {
        new PluginSessionStream(options).start();

        latestSource().emit('status', { session_id: 9, status: 'end' });
        latestSource().emit('messages', { session_id: 9, uuid: 'late', name: '', message_data: {} });
        expect(onMessage).toHaveBeenCalledTimes(1);
        expect(onClosed).not.toHaveBeenCalled();

        vi.advanceTimersByTime(TERMINAL_GRACE_MS);
        expect(onClosed).toHaveBeenCalledWith({ reason: 'ended' });
        expect(latestSource().closed).toBe(true);
    });

    it('notifies nothing after close()', () => {
        const stream = new PluginSessionStream(options);
        stream.start();
        const source = latestSource();

        stream.close();
        source.emit('status', { session_id: 9, status: 'end' });
        vi.runAllTimers();

        expect(source.closed).toBe(true);
        expect(onStatus).not.toHaveBeenCalled();
        expect(onClosed).not.toHaveBeenCalled();
    });
});
