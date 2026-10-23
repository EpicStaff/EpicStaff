import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { ActionCode, NodeType, ResourceCode } from '@shared/models';

import { GraphDto } from '../../../../features/flows/models/graph.model';
import { FlowsApiService } from '../../../../features/flows/services/flows-api.service';
import { ToastService } from '../../../../services/notifications';
import { ScheduleTriggerNodeModel } from '../../../core/models/node.model';
import { FlowService } from '../../../services/flow.service';
import { NodeFactoryService } from '../../../services/node-factory.service';
import { SavedFlowStateService } from '../../../services/saved-flow-state.service';
import { ScheduleTriggerRuntimeService } from '../../../services/schedule-trigger-runtime.service';
import { SidePanelService } from '../../../services/side-panel.service';
import { buildFlowModelFromGraphDto } from '../../../utils/load/build-flow-model-from-graph-dto';
import { cloneFlowState, getNodeDiff, hasTriggerNodeWrites } from '../../../utils/save';
import { withGraphScheduleTriggerRuntimeState } from '../../../utils/save/schedule-trigger-runtime-state';
import { liveGraph } from '../../../utils/testing/live-graph.fixture';
import {
    FLOW_ACTIONS_WITH_USE,
    FLOW_ACTIONS_WITHOUT_USE,
    grantPermissions,
} from '../../../utils/testing/permissions.fixture';
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

describe('ScheduleTriggerNodePanelComponent naming', () => {
    function updatedName(nodeName: string): string {
        TestBed.configureTestingModule({
            providers: [{ provide: FlowsApiService, useValue: { getScheduleTriggerNode: vi.fn() } }],
        });
        TestBed.overrideComponent(ScheduleTriggerNodePanelComponent, { set: { template: '', imports: [] } });
        const node = { ...unsavedScheduleNode, id: 'schedule-2', node_name: nodeName, nodeNumber: 2 };
        TestBed.inject(FlowService).setFlow({
            nodes: [{ ...unsavedScheduleNode, node_name: 'Every hour', nodeNumber: 1 }, node],
            connections: [],
        });
        const fixture = TestBed.createComponent(ScheduleTriggerNodePanelComponent);
        fixture.componentRef.setInput('node', node);
        fixture.detectChanges();
        const name = fixture.componentInstance.createUpdatedNode().node_name;
        fixture.destroy();
        return name;
    }

    // The node's schedule is every hour; another node is already called "Every hour".
    it.each(['Schedule Trigger', 'Schedule Trigger #4', 'Every hour #2', 'Every day'])(
        'renames auto-generated "%s" after its schedule, with no suffix, even when the name is taken',
        (nodeName) => {
            expect(updatedName(nodeName)).toBe('Every hour');
        }
    );

    it('keeps a name the user gave it', () => {
        expect(updatedName('Nightly import')).toBe('Nightly import');
    });
});

describe('ScheduleTriggerNodePanelComponent with a node just dropped on the canvas', () => {
    afterEach(() => vi.useRealTimers());

    function openFreshNode() {
        vi.useFakeTimers();
        vi.setSystemTime(new Date(2026, 9, 23, 12, 41, 7));
        TestBed.configureTestingModule({
            providers: [
                provideHttpClient(),
                { provide: FlowsApiService, useValue: { getScheduleTriggerNode: vi.fn() } },
            ],
        });
        TestBed.overrideComponent(ScheduleTriggerNodePanelComponent, { set: { template: '', imports: [] } });
        // After the component override: granting permissions instantiates the test module.
        // Without Flows:Use a trigger node is read-only and the panel disables its whole form.
        grantPermissions({ [ResourceCode.Flows]: FLOW_ACTIONS_WITH_USE });
        const node = TestBed.inject(NodeFactoryService).createNode(
            NodeType.SCHEDULE_TRIGGER
        ) as ScheduleTriggerNodeModel;
        // Hours later: the panel must show the start the canvas shows, not a new one.
        vi.setSystemTime(new Date(2026, 9, 23, 16, 5, 0));
        const fixture = TestBed.createComponent(ScheduleTriggerNodePanelComponent);
        fixture.componentRef.setInput('node', node);
        fixture.detectChanges();
        return fixture;
    }

    it('shows the name, start and inactive state the canvas shows', () => {
        const fixture = openFreshNode();
        const form = fixture.componentInstance.form;

        expect(form.get('node_name')!.value).toBe('Once on 23 Oct 2026 at 13-00');
        expect(form.get('start_date')!.value).toBe('23.10.2026');
        expect(form.get('start_time')!.value).toBe('13:00');
        expect(form.get('is_active')!.value).toBe(false);
        expect(form.get('is_active')!.enabled).toBe(true);
        expect(fixture.componentInstance.isDirty()).toBe(false);
        fixture.destroy();
    });

    it('saves it unchanged when nothing was edited', () => {
        const fixture = openFreshNode();

        const saved = fixture.componentInstance.createUpdatedNode();

        expect(saved.node_name).toBe('Once on 23 Oct 2026 at 13-00');
        expect(saved.data.startDateTime).toBe('2026-10-23T13:00:00');
        expect(saved.data.isActive).toBe(false);
        fixture.destroy();
    });

    it('renames it after a new start time', () => {
        const fixture = openFreshNode();

        fixture.componentInstance.form.get('start_time')!.setValue('15:30');
        const saved = fixture.componentInstance.createUpdatedNode();

        expect(saved.node_name).toBe('Once on 23 Oct 2026 at 15-30');
        fixture.destroy();
    });
});

describe('ScheduleTriggerNodePanelComponent permissions', () => {
    // Repeating weekly, so the weekday buttons show.
    const weeklyScheduleNode: ScheduleTriggerNodeModel = {
        ...unsavedScheduleNode,
        data: { ...unsavedScheduleNode.data, intervalUnit: 'weeks' },
    };

    function open(flowActions: ActionCode[]) {
        TestBed.configureTestingModule({
            providers: [
                provideHttpClient(),
                // Never called: the node has no backendId.
                { provide: FlowsApiService, useValue: { getScheduleTriggerNode: vi.fn() } },
                { provide: ToastService, useValue: { info: vi.fn() } },
            ],
        });
        grantPermissions({ [ResourceCode.Flows]: flowActions });
        const fixture = TestBed.createComponent(ScheduleTriggerNodePanelComponent);
        fixture.componentRef.setInput('node', weeklyScheduleNode);
        fixture.detectChanges();
        return fixture;
    }

    function element(fixture: ReturnType<typeof open>, selector: string): HTMLElement | null {
        return fixture.nativeElement.querySelector(selector);
    }

    function clickMonday(fixture: ReturnType<typeof open>): void {
        element(fixture, '[data-tooltip="Monday"]')!.click();
        fixture.detectChanges();
    }

    it('is editable for a user who may update and run flows', () => {
        const fixture = open(FLOW_ACTIONS_WITH_USE);

        expect(element(fixture, 'app-custom-input input')).not.toBeNull();
        expect(element(fixture, 'app-radio-button')).not.toBeNull();
        clickMonday(fixture);
        expect(element(fixture, '[data-tooltip="Monday"]')!.classList).toContain('round-btn--active');
        fixture.destroy();
    });

    it('is read-only without Flows:Use: values shown as text, weekdays cannot be toggled, nothing saved', () => {
        const fixture = open(FLOW_ACTIONS_WITHOUT_USE);

        expect(element(fixture, 'app-custom-input input')).toBeNull();
        expect(element(fixture, 'app-custom-input .readonly-value')!.textContent).toContain('Schedule #1');
        expect(element(fixture, 'app-radio-button')).toBeNull();
        clickMonday(fixture);
        expect(element(fixture, '[data-tooltip="Monday"]')!.classList).not.toContain('round-btn--active');
        // What the panel shell and the canvas take on close, Ctrl+S and a full save.
        expect(fixture.componentInstance.onSave()).toBeNull();
        expect(fixture.componentInstance.captureForValidation()).toBeNull();
        fixture.destroy();
    });
});

describe('ScheduleTriggerNodePanelComponent refresh from the backend', () => {
    afterEach(() => vi.useRealTimers());

    it('moves the saved baseline with a polled is_active, so a user without Flows:Use can still save', () => {
        vi.useFakeTimers();
        const [storedSchedule] = liveGraph.schedule_trigger_node_list;
        // The schedule ran its last time between the panel opening and the next poll: the backend turned it off.
        const finishedSchedule = { ...storedSchedule, is_active: false, current_runs: storedSchedule.current_runs + 1 };
        TestBed.configureTestingModule({
            providers: [
                provideHttpClient(),
                provideHttpClientTesting(),
                { provide: ToastService, useValue: { info: vi.fn() } },
            ],
        });
        grantPermissions({ [ResourceCode.Flows]: FLOW_ACTIONS_WITHOUT_USE });
        const httpMock = TestBed.inject(HttpTestingController);
        const scheduleUrl = (request: { url: string }): boolean =>
            request.url.endsWith(`schedule-trigger-nodes/${storedSchedule.id}/`);
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
        httpMock.expectOne(scheduleUrl).flush(storedSchedule);
        // The poll after the panel's first read of the node (an active schedule with no next run: 1 s).
        vi.advanceTimersByTime(1_000);
        httpMock.expectOne(scheduleUrl).flush(finishedSchedule);

        const canvasNode = flowService.nodes().find((node) => node.id === scheduleNode.id) as ScheduleTriggerNodeModel;
        expect(canvasNode.data.isActive).toBe(false);
        const savedNode = TestBed.inject(SavedFlowStateService).savedNode(scheduleNode.id) as ScheduleTriggerNodeModel;
        expect(savedNode.data.isActive).toBe(false);

        const nodeDiff = getNodeDiff(buildFlowModelFromGraphDto(savedGraph), flowService.getFlowState());
        expect(nodeDiff.scheduleNodes.toUpdate).toEqual([]);
        // What the flows page checks before saving for a user without Flows:Use.
        expect(hasTriggerNodeWrites(nodeDiff)).toBe(false);
        fixture.destroy();
    });
});
