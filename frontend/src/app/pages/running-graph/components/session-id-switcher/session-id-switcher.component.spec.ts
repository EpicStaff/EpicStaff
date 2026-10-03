import { ComponentFixture, TestBed } from '@angular/core/testing';
import { GraphSessionStatus } from '@shared/models';

import { GraphSessionLight } from '../../../../features/flows/services/flows-sessions.service';
import { SessionIdSwitcherComponent } from './session-id-switcher.component';

function session(id: number, isTestRun: boolean): GraphSessionLight {
    return {
        id,
        graph_id: 3,
        graph_name: 'Orders',
        status: GraphSessionStatus.ENDED,
        status_updated_at: '2026-10-01T10:00:00Z',
        created_at: '2026-10-01T10:00:00Z',
        finished_at: '2026-10-01T10:01:00Z',
        trigger: { trigger_type: 'webhook', trigger_id: 1, is_test_run: isTestRun },
    };
}

function createFixture(selectedSessionId: string): ComponentFixture<SessionIdSwitcherComponent> {
    const fixture = TestBed.createComponent(SessionIdSwitcherComponent);
    fixture.componentRef.setInput('sessions', [session(2, true), session(1, false)]);
    fixture.componentRef.setInput('selectedSessionId', selectedSessionId);
    fixture.detectChanges();
    return fixture;
}

function triggerChip(fixture: ComponentFixture<SessionIdSwitcherComponent>): Element | null {
    return (fixture.nativeElement as HTMLElement).querySelector('.session-dropdown-trigger app-test-run-chip');
}

describe('SessionIdSwitcherComponent test run chip', () => {
    it('marks the selected session when it is a test run', () => {
        expect(triggerChip(createFixture('2'))).not.toBeNull();
    });

    it('does not mark the selected session when it is a regular run', () => {
        expect(triggerChip(createFixture('1'))).toBeNull();
    });

    it('marks only the test-run items in the dropdown', () => {
        const fixture = createFixture('1');
        (fixture.nativeElement as HTMLElement).querySelector<HTMLButtonElement>('.session-dropdown-trigger')?.click();
        fixture.detectChanges();

        const items = Array.from((fixture.nativeElement as HTMLElement).querySelectorAll('.session-dropdown__item'));
        expect(items.map((item) => item.querySelector('app-test-run-chip') !== null)).toEqual([true, false]);
    });
});
