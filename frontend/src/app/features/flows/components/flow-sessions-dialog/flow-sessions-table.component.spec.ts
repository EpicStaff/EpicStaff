import { CommonModule } from '@angular/common';
import { CUSTOM_ELEMENTS_SCHEMA } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { HasPermissionDirective } from '@shared/directives';
import { GraphSessionStatus } from '@shared/models';

import { PermissionsService } from '../../../../services/auth/permissions.service';
import { GraphSessionLight, SessionRunType, SessionTrigger } from '../../services/flows-sessions.service';
import { FlowSessionTypeFilterDropdownComponent } from './flow-session-type-filter-dropdown.component';
import { FlowSessionsTableComponent } from './flow-sessions-table.component';

function session(id: number, trigger: SessionTrigger | null): GraphSessionLight {
    return {
        id,
        graph_id: 3,
        graph_name: 'Orders',
        status: GraphSessionStatus.ENDED,
        status_updated_at: '2026-10-01T10:00:00Z',
        created_at: '2026-10-01T10:00:00Z',
        finished_at: '2026-10-01T10:01:00Z',
        trigger,
    };
}

function webhookTrigger(isTestRun: boolean): SessionTrigger {
    return { trigger_type: 'webhook', trigger_id: 1, is_test_run: isTestRun };
}

function render(sessions: GraphSessionLight[], showFlowName = false): ComponentFixture<FlowSessionsTableComponent> {
    const fixture = TestBed.createComponent(FlowSessionsTableComponent);
    fixture.componentRef.setInput('sessions', sessions);
    fixture.componentRef.setInput('showFlowName', showFlowName);
    fixture.detectChanges();
    return fixture;
}

function headerClasses(fixture: ComponentFixture<FlowSessionsTableComponent>): string[] {
    return Array.from((fixture.nativeElement as HTMLElement).querySelectorAll('thead th')).map(
        (header) => header.className
    );
}

describe('FlowSessionsTableComponent type column', () => {
    beforeEach(() => {
        TestBed.configureTestingModule({
            providers: [
                provideRouter([]),
                {
                    provide: PermissionsService,
                    useValue: { can: () => false, canAny: () => false } as unknown as PermissionsService,
                },
            ],
        });
        // The other dropdowns and the preview pull in their own services; the type column is under test.
        TestBed.overrideComponent(FlowSessionsTableComponent, {
            set: {
                imports: [CommonModule, HasPermissionDirective, FlowSessionTypeFilterDropdownComponent],
                schemas: [CUSTOM_ELEMENTS_SCHEMA],
            },
        });
    });

    it('places the Type column between ID and Status, with and without the flow name column', () => {
        expect(headerClasses(render([])).slice(0, 3)).toEqual(['col-id', 'col-type', 'col-status']);
        expect(headerClasses(render([], true)).slice(0, 4)).toEqual(['col-id', 'col-type', 'col-status', 'col-flow']);
    });

    it('renders Test for test runs and Live for live runs and sessions without a trigger', () => {
        const fixture = render([session(3, webhookTrigger(true)), session(2, webhookTrigger(false)), session(1, null)]);

        const typeCells = Array.from((fixture.nativeElement as HTMLElement).querySelectorAll('td.col-type'));
        expect(typeCells.map((cell) => cell.textContent?.trim())).toEqual(['Test', 'Live', 'Live']);
        expect(typeCells.map((cell) => cell.classList.contains('col-type--live'))).toEqual([false, true, true]);
    });

    it('keeps only the trigger chip in the Trigger column', () => {
        const fixture = render([session(2, webhookTrigger(true))]);

        const triggerCell = (fixture.nativeElement as HTMLElement).querySelector('td.col-trigger');
        expect(triggerCell?.textContent?.trim()).toBe('Webhook');
        expect(triggerCell?.querySelector('app-test-run-chip')).toBeNull();
    });

    it('spans the empty state across every column, including Type', () => {
        const fixture = render([]);
        fixture.componentRef.setInput('showEmptyState', true);
        fixture.detectChanges();

        const emptyCell = (fixture.nativeElement as HTMLElement).querySelector('tbody td');
        expect(emptyCell?.getAttribute('colspan')).toBe(String(headerClasses(fixture).length));
    });

    it('re-emits the Type filter selection', () => {
        const fixture = render([]);
        const emitted: SessionRunType[][] = [];
        fixture.componentInstance.runTypeFilterChange.subscribe((value) => emitted.push(value));

        const dropdown = fixture.debugElement.query(
            (element) => element.componentInstance instanceof FlowSessionTypeFilterDropdownComponent
        ).componentInstance as FlowSessionTypeFilterDropdownComponent;
        dropdown.valueChange.emit(['test']);

        expect(emitted).toEqual([['test']]);
    });
});
