// The Weather page's pure code: what it reads from the backend, how it shows a temperature, when it says Weather is
// being updated. Node runs the TypeScript sources directly (type stripping); the page's build type-checks them.
import assert from 'node:assert/strict';
import { describe, test } from 'node:test';

import { listPlaces, parseConditions } from '../src/api.ts';
import { AVAILABILITY_PROBE_PATH, checkAvailabilityAgain, showsMaintenance } from '../src/availability.ts';
import { conditionsText } from '../src/conditions.ts';

const NOW = Date.parse('2026-10-21T10:20:00Z');

function place(overrides = {}) {
    return {
        id: 1,
        name: 'Lisbon',
        admin1: 'Lisbon',
        country: 'Portugal',
        latitude: 38.72,
        longitude: -9.14,
        created_at: '2026-10-21T08:00:00Z',
        position: 1,
        conditions: { temperature_c: 12.4, observed_at: '2026-10-21T10:15:00Z' },
        ...overrides,
    };
}

function answer(status, body) {
    return async () => new Response(JSON.stringify(body), { status, headers: { 'content-type': 'application/json' } });
}

describe('listPlaces', () => {
    test('keeps the backend’s order and each place’s conditions', async () => {
        const result = await listPlaces(
            answer(200, { places: [place(), place({ id: 2, name: 'Porto', position: 2, conditions: null })] })
        );

        assert.equal(result.ok, true);
        assert.deepEqual(
            result.value.map((saved) => [saved.name, saved.conditions]),
            [
                ['Lisbon', { temperature_c: 12.4, observed_at: '2026-10-21T10:15:00Z' }],
                ['Porto', null],
            ]
        );
    });

    test('reads conditions it does not understand as none, without failing the list', async () => {
        const result = await listPlaces(
            answer(200, {
                places: [
                    place({ conditions: { temperature_c: '12.4', observed_at: '2026-10-21T10:15:00Z' } }),
                    place({ id: 2, conditions: { temperature_c: 3 } }),
                    place({ id: 3, conditions: 'sunny' }),
                    place({ id: 4, conditions: undefined }),
                ],
            })
        );

        assert.equal(result.ok, true);
        assert.deepEqual(
            result.value.map((saved) => saved.conditions),
            [null, null, null, null]
        );
    });

    test('still refuses a list whose places are not places', async () => {
        const result = await listPlaces(answer(200, { places: [place({ id: 'x' })] }));

        assert.equal(result.ok, false);
        assert.equal(result.code, 'unexpected');
    });
});

describe('parseConditions', () => {
    test('takes a number of degrees and a time, and nothing else', () => {
        assert.deepEqual(parseConditions({ temperature_c: -3, observed_at: '2026-10-21T10:15:00+01:00' }), {
            temperature_c: -3,
            observed_at: '2026-10-21T10:15:00+01:00',
        });
        for (const value of [
            null,
            {},
            { temperature_c: Number.NaN, observed_at: '2026-10-21T10:15:00Z' },
            { temperature_c: 12, observed_at: 'yesterday' },
        ]) {
            assert.equal(parseConditions(value), null, JSON.stringify(value));
        }
    });
});

describe('conditionsText', () => {
    test('shows one decimal and how long ago Weather looked it up', () => {
        const at = (minutesAgo) => new Date(NOW - minutesAgo * 60_000).toISOString();
        assert.equal(conditionsText({ temperature_c: 12.4, observed_at: at(5) }, NOW), '12.4 °C · 5 min ago');
        assert.equal(conditionsText({ temperature_c: -3, observed_at: at(0.5) }, NOW), '-3.0 °C · just now');
        assert.equal(conditionsText({ temperature_c: 20, observed_at: at(125) }, NOW), '20.0 °C · 2 h ago');
        assert.equal(conditionsText({ temperature_c: 20, observed_at: at(60 * 24) }, NOW), '20.0 °C · 1 day ago');
        assert.equal(conditionsText({ temperature_c: 20, observed_at: at(60 * 72) }, NOW), '20.0 °C · 3 days ago');
    });

    test('shows a dash while there is no temperature', () => {
        assert.equal(conditionsText(null, NOW), '—');
    });
});

describe('while Weather is being updated', () => {
    test('the page says so itself only when it runs on its own', () => {
        assert.equal(showsMaintenance(false, 'maintenance', 'maintenance'), true);
        assert.equal(showsMaintenance(false, 'maintenance', 'signed-in'), true);
        assert.equal(showsMaintenance(true, 'maintenance', 'maintenance'), false);
        assert.equal(showsMaintenance(false, 'unavailable', 'signed-in'), false);
        assert.equal(showsMaintenance(false, 'available', 'signed-in'), false);
    });

    test('a denied, ended or failed sign-in is shown instead of the update', () => {
        for (const state of ['access-denied', 'session-ended', 'failed']) {
            assert.equal(showsMaintenance(false, 'maintenance', state), false, state);
        }
    });

    test('checking again signs in again when that was refused, then asks the backend', async () => {
        const calls = [];
        const login = {
            state: 'maintenance',
            async renew() {
                calls.push('renew');
                this.state = 'signed-in';
                return this.state;
            },
            async fetch(path) {
                calls.push(path);
                return new Response('{}');
            },
        };

        await checkAvailabilityAgain(login);

        assert.deepEqual(calls, ['renew', AVAILABILITY_PROBE_PATH]);
    });

    test('checking again while the sign-in is still refused asks the backend nothing', async () => {
        const calls = [];
        const login = {
            state: 'maintenance',
            async renew() {
                calls.push('renew');
                return this.state;
            },
            async fetch(path) {
                calls.push(path);
                return new Response('{}');
            },
        };

        await checkAvailabilityAgain(login);

        assert.deepEqual(calls, ['renew']);
    });

    test('a signed-in page only asks the backend', async () => {
        const calls = [];
        const login = {
            state: 'signed-in',
            async renew() {
                calls.push('renew');
                return this.state;
            },
            async fetch(path) {
                calls.push(path);
                return new Response('{}');
            },
        };

        await checkAvailabilityAgain(login);

        assert.deepEqual(calls, [AVAILABILITY_PROBE_PATH]);
    });
});
