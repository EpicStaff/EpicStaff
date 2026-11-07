import { TestBed } from '@angular/core/testing';

import { FinishStopReason, MessageType } from '../../../../models/graph-session-message.model';
import { FinishMessageComponent } from './finish-message.component';

function render(stopReason: FinishStopReason): HTMLElement {
    const fixture = TestBed.createComponent(FinishMessageComponent);
    fixture.componentRef.setInput('message', {
        id: 1,
        session: 1,
        name: 'Agent #1 #4',
        execution_order: 1,
        created_at: '2026-11-04T00:00:00Z',
        metadata: {},
        message_data: {
            message_type: MessageType.FINISH,
            output: { message: 'partial summary', stop_reason: stopReason },
            state: {},
        },
    });
    fixture.componentRef.setInput('nodeName', 'Agent #1 #4');
    fixture.detectChanges();
    return fixture.nativeElement as HTMLElement;
}

describe('FinishMessageComponent', () => {
    it.each<{ stopReason: FinishStopReason; badge: string }>([
        { stopReason: 'completed', badge: 'Completed' },
        { stopReason: 'max_tool_calls_reached', badge: 'Stopped: too many tool calls.' },
        { stopReason: 'max_consecutive_failures', badge: 'Stopped: too many tool errors in a row.' },
    ])('labels an agent that finished with $stopReason "$badge"', ({ stopReason, badge }) => {
        const element = render(stopReason);

        expect(element.querySelector('.stop-reason-badge')?.textContent?.trim()).toBe(badge);
    });
});
