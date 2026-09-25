import { TestBed } from '@angular/core/testing';
import { NodeType } from '@shared/models';

import { FlowsApiService } from '../../../../features/flows/services/flows-api.service';
import { ScheduleTriggerNodeModel } from '../../../core/models/node.model';
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
