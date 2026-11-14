import { GetScheduleTriggerNodeRequest } from '../../../core/models/schedule-trigger.model';
import { liveGraph } from '../../testing/live-graph.fixture';
import { mapScheduleTriggerNodeToModel, rewriteLegacyOnceScheduleName } from './schedule-trigger-node.mapper';

describe('rewriteLegacyOnceScheduleName', () => {
    it.each([
        { name: 'Once on 01 Jul 2026 at 12:30', rewritten: 'Once on 01 Jul 2026 at 12-30' },
        { name: 'Once on 01 Jul 2026 at 12-30', rewritten: 'Once on 01 Jul 2026 at 12-30' },
        // A legacy uniqueness suffix is kept; the panel regenerates a clean name on the next edit.
        { name: 'Once on 01 Jul 2026 at 12:30 #2', rewritten: 'Once on 01 Jul 2026 at 12-30 #2' },
        { name: 'Nightly import', rewritten: 'Nightly import' },
    ])('rewrites "$name" to "$rewritten"', ({ name, rewritten }) => {
        expect(rewriteLegacyOnceScheduleName(name)).toBe(rewritten);
    });
});

describe('mapScheduleTriggerNodeToModel missed run', () => {
    const [storedSchedule] = liveGraph.schedule_trigger_node_list;

    it.each([
        { missedRunAt: '2026-10-14T09:00:00', expected: '2026-10-14T09:00:00' },
        { missedRunAt: null, expected: null },
    ])('maps the backend missed_run_at $missedRunAt to missedRunAt $expected', ({ missedRunAt, expected }) => {
        const dto: GetScheduleTriggerNodeRequest = {
            ...storedSchedule,
            schedule: { ...storedSchedule.schedule!, missed_run_at: missedRunAt },
        };

        expect(mapScheduleTriggerNodeToModel(dto).data.missedRunAt).toBe(expected);
    });

    it('has no missed run for a draft saved without a schedule', () => {
        expect(mapScheduleTriggerNodeToModel({ ...storedSchedule, schedule: null }).data.missedRunAt).toBeNull();
    });
});
