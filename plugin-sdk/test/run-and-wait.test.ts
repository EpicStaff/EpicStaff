import assert from 'node:assert/strict';
import { afterEach, describe, test } from 'node:test';

import { connect, type EpicStaffBridge, FlowRunError } from '../dist/index.js';
import { createMockHost } from '../dist/mock-host.js';
import {
    delay,
    FakeWindow,
    frameWithHost,
    frameWithScriptedHost,
    type ScriptedHost,
    type ScriptedRequest,
    waitFor,
} from './helpers/fake-window.ts';

const cleanups: Array<() => void> = [];
afterEach(() => {
    while (cleanups.length > 0) cleanups.pop()?.();
});

async function connectTo(win: FakeWindow): Promise<EpicStaffBridge> {
    const bridge = await connect({ window: win.asWindow(), navSync: false });
    cleanups.push(() => bridge.close());
    return bridge;
}

/** A scripted EpicStaff: `flows.run` → session 7, `sessions.subscribe` → `sub-1`, then `afterSubscribe`. */
function sessionHost(win: FakeWindow, afterSubscribe: (host: ScriptedHost) => void): ScriptedHost {
    return frameWithScriptedHost(win, (request: ScriptedRequest, host) => {
        if (request.method === 'flows.run') host.reply(request, { session_id: 7 });
        else if (request.method === 'sessions.subscribe') {
            host.reply(request, { subscription: 'sub-1' });
            afterSubscribe(host);
        } else host.reply(request, {});
    });
}

/** Captures what the SDK reports for a throwing callback (Node has no `reportError`, so `console.error`). */
function captureReports(): unknown[] {
    const reported: unknown[] = [];
    const original = console.error;
    console.error = (error: unknown) => {
        reported.push(error);
    };
    cleanups.push(() => {
        console.error = original;
    });
    return reported;
}

function boom(): never {
    throw new Error('callback failed');
}

function graphEnd(output: unknown): Record<string, unknown> {
    return {
        message_type: 'graph_end',
        name: 'End',
        created_at: null,
        message_data: { message_type: 'graph_end', end_node_result: output },
    };
}

describe('flows.runAndWait', () => {
    test('runs, subscribes and resolves with the End node output', async () => {
        const win = new FakeWindow();
        const host = createMockHost({
            flows: {
                chat: (variables) => ({
                    answer: `Hi ${String(variables['question'])}`,
                    conversation_id: variables['conversation_id'],
                }),
            },
            latencyMs: 0,
            closeGraceMs: 0,
        });
        cleanups.push(() => host.close());
        frameWithHost(win, host);
        const bridge = await connectTo(win);

        const messageTypes: Array<string | null> = [];
        let sessionId = 0;
        const output = await bridge.flows.runAndWait(
            'chat',
            { conversation_id: 'c_1', question: 'there' },
            {
                onMessage: (message) => messageTypes.push(message.message_type),
                onSession: (id) => {
                    sessionId = id;
                },
            }
        );

        assert.deepEqual(output, { answer: 'Hi there', conversation_id: 'c_1' });
        assert.ok(sessionId > 0);
        assert.deepEqual(messageTypes, ['graph_end']);
    });

    test('rejects with FlowRunError "failed" on a failed status', async () => {
        const win = new FakeWindow();
        const host = createMockHost({
            flows: {
                chat: () => {
                    throw new Error('LLM key missing');
                },
            },
            latencyMs: 0,
            closeGraceMs: 0,
        });
        cleanups.push(() => host.close());
        frameWithHost(win, host);
        const bridge = await connectTo(win);

        await assert.rejects(bridge.flows.runAndWait('chat'), (error: unknown) => {
            assert.ok(error instanceof FlowRunError);
            assert.equal(error.reason, 'failed');
            assert.equal(error.status, 'error');
            return true;
        });
    });

    test('rejects with "no_output" when the subscription closes without a graph_end', async () => {
        const win = new FakeWindow();
        sessionHost(win, (host) => {
            host.emit('session.status', 'sub-1', { status: 'end' });
            host.emit('subscription.closed', 'sub-1', { reason: 'ended' });
        });
        const bridge = await connectTo(win);

        await assert.rejects(bridge.flows.runAndWait('chat'), {
            name: 'FlowRunError',
            reason: 'no_output',
            sessionId: 7,
            status: 'end',
        });
    });

    test('rejects with "disconnected" when the stream fails', async () => {
        const win = new FakeWindow();
        sessionHost(win, (host) => host.emit('subscription.closed', 'sub-1', { reason: 'error' }));
        const bridge = await connectTo(win);

        await assert.rejects(bridge.flows.runAndWait('chat'), { reason: 'disconnected' });
    });

    test('resolves when graph_end arrives after the final status, and unsubscribes', async () => {
        const win = new FakeWindow();
        const host = sessionHost(win, (scripted) => {
            scripted.emit('session.status', 'sub-1', { status: 'end' });
            scripted.emit('session.message', 'sub-2', graphEnd({ answer: 'not mine' }));
            scripted.emit('session.message', 'sub-1', graphEnd({ answer: 'late but fine' }));
        });
        const bridge = await connectTo(win);

        const output = await bridge.flows.runAndWait('chat', { question: 'q' });

        assert.deepEqual(output, { answer: 'late but fine' });
        await new Promise((resolve) => setTimeout(resolve, 10));
        assert.deepEqual(
            host.requests.map((request) => [request.method, request.params]),
            [
                ['flows.run', { flow: 'chat', variables: { question: 'q' } }],
                ['sessions.subscribe', { session_id: 7 }],
                ['sessions.unsubscribe', { subscription: 'sub-1' }],
            ]
        );
    });

    test('times out with FlowRunError "timeout"', async () => {
        const win = new FakeWindow();
        sessionHost(win, () => undefined);
        const bridge = await connectTo(win);

        await assert.rejects(bridge.flows.runAndWait('chat', {}, { timeoutMs: 20 }), { reason: 'timeout' });
    });

    test('passes a bridge failure of flows.run through as BridgeCallError', async () => {
        const win = new FakeWindow();
        const host = createMockHost({ flows: { chat: () => ({}) }, latencyMs: 0 });
        cleanups.push(() => host.close());
        frameWithHost(win, host);
        const bridge = await connectTo(win);

        await assert.rejects(bridge.flows.runAndWait('unknown-flow'), { name: 'BridgeCallError', code: 'forbidden' });
    });

    test('a throwing onMessage or onSession does not change the outcome', async () => {
        const reported = captureReports();
        const win = new FakeWindow();
        sessionHost(win, (host) => host.emit('session.message', 'sub-1', graphEnd({ answer: 'still here' })));
        const bridge = await connectTo(win);

        const output = await bridge.flows.runAndWait('chat', {}, { onMessage: boom, onSession: boom });

        assert.deepEqual(output, { answer: 'still here' });
        assert.equal(reported.length, 2, 'both callback errors are reported');
    });

    test('a throwing onStatus still rejects with "failed", not "no_output"', async () => {
        captureReports();
        const win = new FakeWindow();
        sessionHost(win, (host) => {
            host.emit('session.status', 'sub-1', { status: 'error' });
            host.emit('subscription.closed', 'sub-1', { reason: 'ended' });
        });
        const bridge = await connectTo(win);

        await assert.rejects(bridge.flows.runAndWait('chat', {}, { onStatus: boom }), {
            reason: 'failed',
            status: 'error',
        });
    });

    test('events that arrive before the subscribe answer are replayed through the same guard', async () => {
        const reported = captureReports();
        const win = new FakeWindow();
        frameWithScriptedHost(win, (request, host) => {
            if (request.method === 'flows.run') host.reply(request, { session_id: 7 });
            else if (request.method === 'sessions.subscribe') {
                // Events first, the answer second: the client has to buffer and replay them.
                host.emit('session.status', 'sub-1', { status: 'run' });
                host.emit('session.message', 'sub-1', graphEnd({ answer: 'replayed' }));
                host.reply(request, { subscription: 'sub-1' });
            } else host.reply(request, {});
        });
        const bridge = await connectTo(win);

        const output = await bridge.flows.runAndWait('chat', {}, { onMessage: boom, onStatus: boom });

        assert.deepEqual(output, { answer: 'replayed' });
        assert.equal(reported.length, 2);
    });

    test('close() rejects a waiting run at once with "closed"', async () => {
        const win = new FakeWindow();
        const host = sessionHost(win, () => undefined);
        const bridge = await connectTo(win);

        const run = bridge.flows.runAndWait('chat');
        await waitFor(() => host.requests.some((request) => request.method === 'sessions.subscribe'));
        await delay(5);
        bridge.close();

        const outcome = await Promise.race([
            run.then(
                () => 'resolved',
                (error: unknown) => error
            ),
            delay(200).then(() => 'still waiting'),
        ]);
        assert.ok(outcome instanceof Error, `expected a rejection, got ${String(outcome)}`);
        assert.equal((outcome as { code?: string }).code, 'closed');
    });
});
