import { ComponentFixture, TestBed } from '@angular/core/testing';
import { ICellRendererParams } from 'ag-grid-community';

import { ConditionGroup } from '../../../../../core/models/decision-table.model';
import { CDT_ROUTE_CONTINUE_COPY } from '../../cdt.constants';
import { RouteCodeCellRendererComponent, routeCodeCellStatus } from './route-code-cell-renderer.component';

function row(overrides: Partial<ConditionGroup>): ConditionGroup {
    return {
        group_name: 'Condition 1',
        group_type: 'complex',
        expression: null,
        conditions: [],
        manipulation: null,
        next_node: null,
        ...overrides,
    };
}

function params(data: ConditionGroup): ICellRendererParams<ConditionGroup, string> {
    return { value: data.route_code, data } as ICellRendererParams<ConditionGroup, string>;
}

/** The sprite symbol the status icon points at, e.g. `#icon-alert-circle`. */
function renderedIcon(element: HTMLElement): string | null {
    return element.querySelector('.cdt-route-code-cell__status use')?.getAttribute('href') ?? null;
}

function render(data: ConditionGroup): ComponentFixture<RouteCodeCellRendererComponent> {
    const fixture = TestBed.createComponent(RouteCodeCellRendererComponent);
    fixture.componentInstance.agInit(params(data));
    fixture.detectChanges();
    return fixture;
}

describe('routeCodeCellStatus', () => {
    it('flags a row with both a route code and Continue', () => {
        expect(routeCodeCellStatus(row({ route_code: 'approve', continue_flag: true }))).toEqual({
            icon: 'alert-triangle',
            message: CDT_ROUTE_CONTINUE_COPY.continueIgnored,
        });
    });

    it('reads the legacy continue key', () => {
        expect(routeCodeCellStatus(row({ route_code: 'approve', continue: true }))?.icon).toBe('alert-triangle');
        expect(routeCodeCellStatus(row({ route_code: '', continue: true }))).toBeNull();
    });

    it('leaves a row with neither to the red cell border', () => {
        expect(routeCodeCellStatus(row({ route_code: '', continue_flag: false }))).toBeNull();
        expect(routeCodeCellStatus(row({ route_code: '   ', continue_flag: false }))).toBeNull();
    });

    it('has nothing to say about a missing row', () => {
        expect(routeCodeCellStatus(undefined)).toBeNull();
    });

    it('has nothing to say about a row that uses exactly one', () => {
        expect(routeCodeCellStatus(row({ route_code: 'approve', continue_flag: false }))).toBeNull();
        expect(routeCodeCellStatus(row({ route_code: '', continue_flag: true }))).toBeNull();
    });
});

describe('RouteCodeCellRendererComponent', () => {
    it('shows the code and no icon on a valid row', () => {
        const element: HTMLElement = render(row({ route_code: 'approve', continue_flag: false })).nativeElement;

        expect(element.querySelector('.cdt-route-code-cell__code')?.textContent).toBe('approve');
        expect(element.querySelector('.cdt-route-code-cell__status')).toBeNull();
    });

    it('shows no icon on a row with neither', () => {
        const element: HTMLElement = render(row({ route_code: '', continue_flag: false })).nativeElement;

        expect(element.querySelector('.cdt-route-code-cell__status')).toBeNull();
    });

    it('shows a warning icon labelled with the message when Continue is ignored', () => {
        const element: HTMLElement = render(row({ route_code: 'approve', continue_flag: true })).nativeElement;
        const status = element.querySelector('.cdt-route-code-cell__status');

        expect(status?.getAttribute('role')).toBe('img');
        expect(status?.getAttribute('aria-label')).toBe(CDT_ROUTE_CONTINUE_COPY.continueIgnored);
        expect(renderedIcon(element)).toBe('#icon-alert-triangle');
    });

    it('updates the icon on refresh, as refreshCells does after a Continue change', () => {
        const fixture = render(row({ route_code: 'approve', continue_flag: true }));
        const element = fixture.nativeElement as HTMLElement;
        expect(element.querySelector('.cdt-route-code-cell__status')).not.toBeNull();

        expect(fixture.componentInstance.refresh(params(row({ route_code: 'approve', continue_flag: false })))).toBe(
            true
        );
        fixture.detectChanges();

        expect(element.querySelector('.cdt-route-code-cell__status')).toBeNull();
    });
});
