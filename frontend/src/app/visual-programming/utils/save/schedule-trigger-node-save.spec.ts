import { TestBed } from '@angular/core/testing';
import { NodeType } from '@shared/models';

import { FlowModel } from '../../core/models/flow.model';
import { FlowSettingsService } from '../../services/flow-settings.service';
import { NodeFactoryService } from '../../services/node-factory.service';
import { buildUuidToBackendIdMap, getConnectionDiff, getNodeDiff } from './diff';
import { buildBulkSavePayload } from './payload';

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
