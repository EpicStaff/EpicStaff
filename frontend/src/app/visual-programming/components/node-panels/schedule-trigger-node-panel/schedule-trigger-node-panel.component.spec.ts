import { TestBed } from '@angular/core/testing';
import { NodeType } from '@shared/models';

import { FlowsApiService } from '../../../../features/flows/services/flows-api.service';
import { ScheduleTriggerNodeModel } from '../../../core/models/node.model';
import { FlowService } from '../../../services/flow.service';
import { SidePanelService } from '../../../services/side-panel.service';
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
