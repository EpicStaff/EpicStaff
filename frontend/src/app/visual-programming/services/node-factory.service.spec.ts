import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { signal } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { GetMeResponse, NodeType } from '@shared/models';

import { ProfileService } from '../../services/auth/profile.service';
import { API_URL, memberOf, ORGANIZATION_A } from '../../services/auth/testing/current-user-fixtures';
import { ConfigService } from '../../services/config';
import { DEFAULT_NODE_DATA } from '../core/constants/default-node-data';
import { NodeModel, ScheduleTriggerNodeModel } from '../core/models/node.model';
import { ScheduleTriggerNodeData } from '../core/models/schedule-trigger.model';
import { FlowService } from './flow.service';
import { FlowViewOverrideService } from './flow-view-override.service';
import { NodeFactoryService } from './node-factory.service';

/** Signs in a user whose default timezone for new schedules is `zone`; replaces the profile before anything reads it. */
function signInWithDefaultTimezone(zone: string): void {
    const user = memberOf(ORGANIZATION_A);
    const signedIn: GetMeResponse = {
        ...user,
        preferences: { ...user.preferences, general: { ...user.preferences.general, default_timezone: zone } },
    };
    TestBed.resetTestingModule();
    TestBed.configureTestingModule({
        providers: [
            provideHttpClient(),
            provideHttpClientTesting(),
            { provide: ConfigService, useValue: { apiUrl: API_URL } as unknown as ConfigService },
            { provide: ProfileService, useValue: { currentUserSignal: signal(signedIn) } },
        ],
    });
}

/** Opens flow 5 with the signed-in user's own zone for its new schedule triggers. */
function openFlowWithScheduleZone(zone: string): void {
    TestBed.inject(FlowViewOverrideService).load(5);
    TestBed.inject(HttpTestingController)
        .expectOne({ method: 'GET', url: '/api/graphs/5/my-view-settings/' })
        .flush({ settings: { default_timezone: zone } });
}

function createScheduleTrigger(overrides?: Partial<NodeModel>): ScheduleTriggerNodeModel {
    return TestBed.inject(NodeFactoryService).createNode(
        NodeType.SCHEDULE_TRIGGER,
        overrides
    ) as ScheduleTriggerNodeModel;
}

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

    it('new python node starts with every box false', () => {
        const created = factory.createNode(NodeType.PYTHON);

        expect(created.storageGrants).toEqual({ read: false, write: false, delete: false });
    });

    it('gives a node type that has no grants no storage grants', () => {
        expect(factory.createNode(NodeType.TASK).storageGrants).toBeUndefined();
        expect(factory.createNode(NodeType.AGENT).storageGrants).toBeUndefined();
        expect(factory.createNode(NodeType.FILE_EXTRACTOR).storageGrants).toBeUndefined();
        expect(factory.createNode(NodeType.AUDIO_TO_TEXT).storageGrants).toBeUndefined();
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

        it("runs in the flow's own zone, ahead of the account's default", () => {
            signInWithDefaultTimezone('Asia/Tokyo');
            openFlowWithScheduleZone('America/New_York');

            expect(createScheduleTrigger().data.timezone).toBe('America/New_York');
        });

        it("keeps the zone of a trigger it copies, whatever the flow's zone", () => {
            signInWithDefaultTimezone('Asia/Tokyo');
            openFlowWithScheduleZone('America/New_York');
            const copied: ScheduleTriggerNodeData = {
                ...(DEFAULT_NODE_DATA[NodeType.SCHEDULE_TRIGGER]!() as ScheduleTriggerNodeData),
                timezone: 'Europe/Kyiv',
            };

            expect(createScheduleTrigger({ data: copied }).data.timezone).toBe('Europe/Kyiv');
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

describe('NodeFactoryService node uuid', () => {
    let factory: NodeFactoryService;

    beforeEach(() => {
        factory = TestBed.inject(NodeFactoryService);
    });

    it('gives every created node its own uuid', () => {
        const first = factory.createNode(NodeType.PYTHON);
        const second = factory.createNode(NodeType.PYTHON);

        expect(first.nodeUuid).toEqual(expect.any(String));
        expect(second.nodeUuid).toEqual(expect.any(String));
        expect(first.nodeUuid).not.toBe(second.nodeUuid);
        expect(first.nodeUuid).not.toBe(first.id);
    });

    it('gives a new uuid even when the overrides carry one', () => {
        const node = factory.createNode(NodeType.NOTE, { nodeUuid: 'copied-node-uuid' });

        expect(node.nodeUuid).toEqual(expect.any(String));
        expect(node.nodeUuid).not.toBe('copied-node-uuid');
    });
});
