import { TestBed } from '@angular/core/testing';
import { ActionCode, NodeType } from '@shared/models';
import { of } from 'rxjs';

import { GraphDto } from '../../../../features/flows/models/graph.model';
import { FlowsApiService } from '../../../../features/flows/services/flows-api.service';
import { PermissionsService } from '../../../../services/auth/permissions.service';
import { ToastService } from '../../../../services/notifications';
import { ScheduleTriggerNodeModel } from '../../../core/models/node.model';
import { FlowService } from '../../../services/flow.service';
import { SavedFlowStateService } from '../../../services/saved-flow-state.service';
import { ScheduleTriggerRuntimeService } from '../../../services/schedule-trigger-runtime.service';
import { SidePanelService } from '../../../services/side-panel.service';
import { buildFlowModelFromGraphDto } from '../../../utils/load/build-flow-model-from-graph-dto';
import { cloneFlowState, getNodeDiff, hasTriggerNodeWrites } from '../../../utils/save';
import { withGraphScheduleTriggerRuntimeState } from '../../../utils/save/schedule-trigger-runtime-state';
import { liveGraph } from '../../../utils/testing/live-graph.fixture';
import { ScheduleTriggerNodePanelComponent } from './schedule-trigger-node-panel.component';

// A node without a backendId — what a version preview renders — must never reach the
// schedule API: not on open, not from the poll timer, not after a graph save.
const unsavedScheduleNode: ScheduleTriggerNodeModel = {
    id: 'schedule-1',
    backendId: null,
    type: NodeType.SCHEDULE_TRIGGER,
    node_name: 'Schedule #1',
    data: {
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
        nextRunDateTime: null,
    },
    position: { x: 0, y: 0 },
    ports: null,
    color: '',
    icon: '',
    size: { width: 200, height: 100 },
    input_map: {},
    output_variable_path: null,
};

describe('ScheduleTriggerNodePanelComponent with backendId null', () => {
    afterEach(() => vi.useRealTimers());

    it('never calls getScheduleTriggerNode', () => {
        vi.useFakeTimers();
        const getScheduleTriggerNode = vi.fn();
        TestBed.configureTestingModule({
            providers: [{ provide: FlowsApiService, useValue: { getScheduleTriggerNode } }],
        });
        TestBed.overrideComponent(ScheduleTriggerNodePanelComponent, { set: { template: '', imports: [] } });

        const fixture = TestBed.createComponent(ScheduleTriggerNodePanelComponent);
        fixture.componentRef.setInput('node', unsavedScheduleNode);
        fixture.detectChanges();

        vi.advanceTimersByTime(10 * 60_000);
        TestBed.inject(SidePanelService).notifyGraphSaved();
        vi.advanceTimersByTime(10 * 60_000);

        expect(getScheduleTriggerNode).not.toHaveBeenCalled();
        fixture.destroy();
    });

    it('disables the timezone selector when the panel form is disabled (read-only preview)', () => {
        TestBed.configureTestingModule({
            providers: [{ provide: FlowsApiService, useValue: { getScheduleTriggerNode: vi.fn() } }],
        });
        const fixture = TestBed.createComponent(ScheduleTriggerNodePanelComponent);
        fixture.componentRef.setInput('node', unsavedScheduleNode);
        fixture.detectChanges();

        fixture.componentInstance.form.disable({ emitEvent: false });
        fixture.detectChanges();

        const timezoneButton = fixture.nativeElement.querySelector('.tz-selector__btn') as HTMLButtonElement;
        expect(timezoneButton).not.toBeNull();
        expect(timezoneButton.disabled).toBe(true);
        fixture.destroy();
    });
});

describe('ScheduleTriggerNodePanelComponent permissions', () => {
    function open(canRunFlows: boolean): ScheduleTriggerNodePanelComponent {
        TestBed.configureTestingModule({
            providers: [
                { provide: FlowsApiService, useValue: { getScheduleTriggerNode: vi.fn() } },
                { provide: ToastService, useValue: { info: vi.fn() } },
                {
                    provide: PermissionsService,
                    useValue: {
                        can: (_resource: unknown, action: ActionCode) => action !== ActionCode.Run || canRunFlows,
                    },
                },
            ],
        });
        TestBed.overrideComponent(ScheduleTriggerNodePanelComponent, { set: { template: '', imports: [] } });
        const fixture = TestBed.createComponent(ScheduleTriggerNodePanelComponent);
        fixture.componentRef.setInput('node', unsavedScheduleNode);
        fixture.detectChanges();
        return fixture.componentInstance;
    }

    it('is editable for a user who may update and run flows', () => {
        const panel = open(true);

        expect(panel.isReadOnly()).toBe(false);
        expect(panel.form.enabled).toBe(true);
    });

    it('is read-only without Flows:Run: disabled form, no weekday toggling, nothing saved', () => {
        const panel = open(false);

        panel.toggleDay('mon');

        expect(panel.isReadOnly()).toBe(true);
        expect(panel.form.disabled).toBe(true);
        expect(panel.repeatDays()).toEqual([]);
        expect(panel.isDirty()).toBe(false);
        expect(panel.onSave()).toBeNull();
        expect(panel.captureForValidation()).toBeNull();
    });
});

describe('ScheduleTriggerNodePanelComponent refresh from the backend', () => {
    afterEach(() => vi.useRealTimers());

    it('moves the saved baseline with a polled is_active, so a user without Flows:Run can still save', () => {
        vi.useFakeTimers();
        const [storedSchedule] = liveGraph.schedule_trigger_node_list;
        // The schedule ran its last time between the panel opening and the next poll: the backend turned it off.
        const finishedSchedule = { ...storedSchedule, is_active: false, current_runs: storedSchedule.current_runs + 1 };
        const getScheduleTriggerNode = vi
            .fn()
            .mockReturnValueOnce(of(storedSchedule))
            .mockReturnValue(of(finishedSchedule));
        TestBed.configureTestingModule({
            providers: [
                { provide: FlowsApiService, useValue: { getScheduleTriggerNode } },
                { provide: ToastService, useValue: { info: vi.fn() } },
                {
                    provide: PermissionsService,
                    useValue: { can: (_resource: unknown, action: ActionCode) => action !== ActionCode.Run },
                },
            ],
        });
        TestBed.overrideComponent(ScheduleTriggerNodePanelComponent, { set: { template: '', imports: [] } });
        const flowService = TestBed.inject(FlowService);
        const loadedFlow = buildFlowModelFromGraphDto(liveGraph);
        flowService.setFlow(loadedFlow);
        TestBed.inject(SavedFlowStateService).setSavedFlow(cloneFlowState(loadedFlow));
        // The flows page's part: its saved graph (the save diff's baseline) follows each runtime update.
        let savedGraph: GraphDto = liveGraph;
        TestBed.inject(ScheduleTriggerRuntimeService).updates$.subscribe(({ backendId, state }) => {
            savedGraph = withGraphScheduleTriggerRuntimeState(savedGraph, backendId, state);
        });
        const scheduleNode = loadedFlow.nodes.find(
            (node): node is ScheduleTriggerNodeModel => node.type === NodeType.SCHEDULE_TRIGGER
        )!;
        expect(scheduleNode.data.isActive).toBe(true);

        const fixture = TestBed.createComponent(ScheduleTriggerNodePanelComponent);
        fixture.componentRef.setInput('node', scheduleNode);
        fixture.detectChanges();
        // The poll after the panel's first read of the node (an active schedule with no next run: 1 s).
        vi.advanceTimersByTime(1_000);

        expect(getScheduleTriggerNode).toHaveBeenCalledTimes(2);
        const canvasNode = flowService.nodes().find((node) => node.id === scheduleNode.id) as ScheduleTriggerNodeModel;
        expect(canvasNode.data.isActive).toBe(false);
        const savedNode = TestBed.inject(SavedFlowStateService).savedNode(scheduleNode.id) as ScheduleTriggerNodeModel;
        expect(savedNode.data.isActive).toBe(false);

        const nodeDiff = getNodeDiff(buildFlowModelFromGraphDto(savedGraph), flowService.getFlowState());
        expect(nodeDiff.scheduleNodes.toUpdate).toEqual([]);
        // What the flows page checks before saving for a user without Flows:Run.
        expect(hasTriggerNodeWrites(nodeDiff)).toBe(false);
        fixture.destroy();
    });
});
