import assert from 'node:assert/strict';
import { afterEach, describe, test } from 'node:test';

import { BridgeConnection } from '../dist/connection.js';
import { delay, waitFor } from './helpers/fake-window.ts';

interface SentRequest {
    id: number;
    method: string;
}

const cleanups: Array<() => void> = [];
afterEach(() => {
    while (cleanups.length > 0) cleanups.pop()?.();
});

/** A connection whose other end (EpicStaff) the test drives by hand. */
function openConnection(
    timeoutMs = 30_000,
    abandonedReleaseMs = 60_000
): {
    connection: BridgeConnection;
    host: MessagePort;
    received: SentRequest[];
    answer: (request: SentRequest, result?: unknown) => void;
} {
    const { port1: host, port2: page } = new MessageChannel();
    const received: SentRequest[] = [];
    host.onmessage = (event: MessageEvent) => received.push(event.data as SentRequest);
    const connection = new BridgeConnection(page, timeoutMs, abandonedReleaseMs);
    cleanups.push(() => {
        connection.close();
        host.close();
    });
    const answer = (request: SentRequest, result: unknown = {}): void =>
        host.postMessage({ v: 2, kind: 'response', id: request.id, ok: true, result });
    return { connection, host, received, answer };
}

describe('in-flight accounting', () => {
    test('a call the caller aborted keeps its slot until EpicStaff answers it', async () => {
        const { connection, received, answer } = openConnection();
        const controller = new AbortController();
        const aborted = Array.from({ length: 10 }, () =>
            connection.call('kv.list', { table: 'conversations' }, { signal: controller.signal })
        );
        await waitFor(() => received.length === 10);
        controller.abort();
        for (const call of aborted) await assert.rejects(call, { code: 'aborted' });

        const next = connection.call('bridge.hello');
        await delay(20);
        assert.equal(received.length, 10, 'EpicStaff still counts the 10 aborted requests, so the 11th waits');
        assert.equal(connection.inFlightCount, 10);

        // The late answer to an aborted call frees its slot; the answer itself is dropped.
        answer(received[0] as SentRequest, { count: 0, items: [] });
        await waitFor(() => received.length === 11);
        assert.equal(received[10]?.method, 'bridge.hello');
        answer(received[10] as SentRequest, { bridge_version: 2 });
        assert.deepEqual(await next, { bridge_version: 2 });
    });

    test('a timed-out call is freed by the safety timer when no answer ever comes', async () => {
        const { connection, received } = openConnection(20, 80);
        const timedOut = Array.from({ length: 10 }, () => connection.call('kv.list', { table: 'conversations' }));
        for (const call of timedOut) await assert.rejects(call, { code: 'timeout' });

        const next = connection.call('bridge.hello', {}, { timeoutMs: 5000 });
        next.catch(() => undefined);
        assert.equal(received.length, 10);
        await waitFor(() => received.length === 11);
        assert.equal(received[10]?.method, 'bridge.hello');
    });

    test('a call aborted while still queued is never sent and holds no slot', async () => {
        const { connection, received, answer } = openConnection();
        const held = Array.from({ length: 10 }, () => connection.call('bridge.hello'));
        // The unanswered ones are rejected with "closed" when the test closes the connection.
        held.forEach((call) => call.catch(() => undefined));
        const controller = new AbortController();
        const queued = connection.call('kv.get', { table: 'conversations', key: 'k' }, { signal: controller.signal });
        await waitFor(() => received.length === 10);
        controller.abort();
        await assert.rejects(queued, { code: 'aborted' });

        answer(received[0] as SentRequest);
        await held[0];
        await delay(20);
        assert.equal(received.length, 10, 'the aborted request never left the queue');
        assert.equal(connection.inFlightCount, 9);
    });

    test('an answer to a request that was never sent is ignored', async () => {
        const { connection, host, received, answer } = openConnection();
        const held = Array.from({ length: 10 }, () => connection.call('bridge.hello'));
        // The unanswered ones are rejected with "closed" when the test closes the connection.
        held.forEach((call) => call.catch(() => undefined));
        const queued = connection.call('bridge.hello');
        await waitFor(() => received.length === 10);
        host.postMessage({ v: 2, kind: 'response', id: 11, ok: true, result: { forged: true } });
        await delay(20);
        assert.equal(connection.inFlightCount, 10);

        answer(received[0] as SentRequest);
        await held[0];
        await waitFor(() => received.length === 11);
        answer(received[10] as SentRequest, { genuine: true });
        assert.deepEqual(await queued, { genuine: true });
    });

    test('close() rejects every waiting call and calls close listeners once', async () => {
        const { connection } = openConnection();
        let closed = 0;
        connection.onClose(() => closed++);
        const pending = connection.call('bridge.hello');
        connection.close();
        connection.close();
        await assert.rejects(pending, { code: 'closed' });
        assert.equal(closed, 1);
    });
});
