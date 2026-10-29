import { TestBed } from '@angular/core/testing';
import { NodeType } from '@shared/models';

import { NodeModel, ScheduleTriggerNodeModel } from '../core/models/node.model';
import { ScheduleTriggerNodeData } from '../core/models/schedule-trigger.model';
import { FlowService } from './flow.service';
import { NodeFactoryService } from './node-factory.service';

describe('NodeFactoryService', () => {
    let factory: NodeFactoryService;

    beforeEach(() => {
        const flowService = TestBed.inject(FlowService);
        flowService.setFlow({
            nodes: [
                {
                    id: 'existing',
                    type: NodeType.PYTHON,
                    nodeNumber: 4,
                    position: { x: 900, y: 900 },
                    size: { width: 200, height: 100 },
                } as NodeModel,
            ],
            connections: [],
        });
        flowService.setNodeNumberFloor(4);
        factory = TestBed.inject(NodeFactoryService);
    });

    it('names a new node after its type and keeps the next number out of the name', () => {
        const created = factory.createNode(NodeType.PYTHON);

        expect(created.node_name).toBe('Python-Node');
        expect(created.nodeNumber).toBe(5);
    });

    it.each([NodeType.NOTE, NodeType.START, NodeType.END])('gives a new %s node no number', (type) => {
        expect(factory.createNode(type).nodeNumber).toBeUndefined();
    });

    it('does not use up a number on an unnumbered node', () => {
        factory.createNode(NodeType.NOTE);

        expect(factory.createNode(NodeType.TASK).nodeNumber).toBe(5);
    });

    describe('a schedule trigger node', () => {
        afterEach(() => vi.useRealTimers());

        it('starts as an inactive one-time run at the next half hour, named after it', () => {
            vi.useFakeTimers();
            vi.setSystemTime(new Date(2026, 9, 23, 12, 41, 7));

            const created = factory.createNode(NodeType.SCHEDULE_TRIGGER) as ScheduleTriggerNodeModel;

            expect(created.data.startDateTime).toBe('2026-10-23T13:00:00');
            expect(created.node_name).toBe('Once on 23 Oct 2026 at 13-00');
            expect(created.data.runMode).toBe('once');
            expect(created.data.isActive).toBe(false);
        });

        it('keeps the data and name passed in overrides', () => {
            const givenData: ScheduleTriggerNodeData = {
                isActive: true,
                runMode: 'repeat',
                startDateTime: '2026-07-01T12:00:00',
                intervalEvery: 1,
                intervalUnit: 'hours',
                weekdays: [],
                endType: 'never',
                endDateTime: null,
                maxRuns: null,
                timezone: 'Europe/Kyiv',
            };

            const created = factory.createNode(NodeType.SCHEDULE_TRIGGER, {
                node_name: 'Nightly import',
                data: givenData,
            }) as ScheduleTriggerNodeModel;

            expect(created.node_name).toBe('Nightly import');
            expect(created.data.startDateTime).toBe('2026-07-01T12:00:00');
            expect(created.data.runMode).toBe('repeat');
            expect(created.data.isActive).toBe(true);
        });
    });
});
