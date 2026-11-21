import { TestBed } from '@angular/core/testing';
import { NodeType } from '@shared/models';

import { GraphDto } from '../../../features/flows/models/graph.model';
import { FlowModel } from '../../core/models/flow.model';
import { ScheduleTriggerNodeModel } from '../../core/models/node.model';
import { GetScheduleTriggerNodeRequest } from '../../core/models/schedule-trigger.model';
import { FlowSettingsService } from '../../services/flow-settings.service';
import { NodeFactoryService } from '../../services/node-factory.service';
import { mapScheduleTriggerNodeToModel } from '../load/nodes/schedule-trigger-node.mapper';
import { liveGraph } from '../testing/live-graph.fixture';
import { buildUuidToBackendIdMap, getConnectionDiff, getNodeDiff } from './diff';
import { patchFlowStateWithBackendIds, patchLiveFlowWithBackendIds } from './patch';
import { buildBulkSavePayload } from './payload';

const MISSED_RUN_AT = '2026-10-14T09:00:00';
const [storedSchedule] = liveGraph.schedule_trigger_node_list;

/** The stored schedule as the backend returns it, its run-once start missed (or not) while the scheduler was down. */
function scheduleRow(missedRunAt: string | null, overrides: Partial<GetScheduleTriggerNodeRequest> = {}) {
    return {
        ...storedSchedule,
        is_active: false,
        ...overrides,
        schedule: { ...storedSchedule.schedule!, missed_run_at: missedRunAt },
    } satisfies GetScheduleTriggerNodeRequest;
}

function flowOf(...nodes: ScheduleTriggerNodeModel[]): FlowModel {
    return { nodes, connections: [] };
}

function payloadOf(previous: FlowModel, current: FlowModel): Record<string, unknown> {
    const idMap = buildUuidToBackendIdMap(current.nodes);
    return buildBulkSavePayload(
        1,
        getNodeDiff(previous, current),
        getConnectionDiff(previous, current, idMap),
        current,
        idMap,
        0
    );
}

describe('saving a schedule trigger node just dropped on the canvas', () => {
    afterEach(() => vi.useRealTimers());

    it('sends an inactive one-time schedule starting at its proposed time', () => {
        vi.useFakeTimers();
        vi.setSystemTime(new Date(2026, 9, 23, 12, 41, 7));
        TestBed.inject(FlowSettingsService).timezone.set('Europe/Kyiv');
        const node = TestBed.inject(NodeFactoryService).createNode(NodeType.SCHEDULE_TRIGGER);
        const previous: FlowModel = { nodes: [], connections: [] };
        const current: FlowModel = { nodes: [node], connections: [] };
        const idMap = buildUuidToBackendIdMap(current.nodes);

        const payload = buildBulkSavePayload(
            1,
            getNodeDiff(previous, current),
            getConnectionDiff(previous, current, idMap),
            current,
            idMap,
            0
        );

        const [sent] = payload['schedule_trigger_node_list'] as Record<string, unknown>[];
        expect(sent['node_name']).toBe('Once on 23 Oct 2026 at 13-00');
        expect(sent['is_active']).toBe(false);
        expect(sent['schedule']).toEqual({
            run_mode: 'once',
            start_date_time: '2026-10-23T13:00:00',
            interval: null,
            end: { type: 'never', date_time: null, max_runs: null },
            timezone: 'Europe/Kyiv',
        });
    });
});

describe('saving a schedule trigger node whose run was missed', () => {
    const saved = mapScheduleTriggerNodeToModel(scheduleRow(MISSED_RUN_AT));

    it('never sends the missed run, which only the backend sets', () => {
        const payload = payloadOf(flowOf(saved), flowOf({ ...saved, node_name: 'Nightly' }));

        const sent = payload['schedule_trigger_node_list'] as Record<string, unknown>[];
        expect(sent).toHaveLength(1);
        expect(sent[0]['node_name']).toBe('Nightly');
        expect(JSON.stringify(sent[0])).not.toContain(MISSED_RUN_AT);
        expect(JSON.stringify(sent[0])).not.toMatch(/missed/i);
    });

    it('does not count a changed missed run as an edit', () => {
        const cleared = { ...saved, data: { ...saved.data, missedRunAt: null } };

        const payload = payloadOf(flowOf(saved), flowOf(cleared));

        expect(payload['schedule_trigger_node_list']).toEqual([]);
    });
});

describe('a schedule trigger node patched from the save response', () => {
    it.each([
        { name: 'clears the missed run the response no longer has', before: MISSED_RUN_AT, response: null },
        { name: 'takes a missed run the response reports', before: null, response: MISSED_RUN_AT },
    ])('$name, in both the sent and the live flow', ({ before, response }) => {
        const saved = mapScheduleTriggerNodeToModel(scheduleRow(before));
        const sent = flowOf({ ...saved, node_name: 'Nightly' });
        const nodeDiff = getNodeDiff(flowOf(saved), sent);
        const responseGraph = {
            schedule_trigger_node_list: [scheduleRow(response, { node_name: 'Nightly' })],
        } as unknown as GraphDto;

        const sentPatched = patchFlowStateWithBackendIds(sent, flowOf(saved), nodeDiff, responseGraph);
        const livePatched = patchLiveFlowWithBackendIds(sent, sentPatched, flowOf(saved), nodeDiff, responseGraph);

        for (const patched of [sentPatched, livePatched]) {
            expect((patched.nodes[0] as ScheduleTriggerNodeModel).data.missedRunAt).toBe(response);
        }
    });
});
