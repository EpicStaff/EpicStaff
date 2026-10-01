import { ComponentFixture, TestBed } from '@angular/core/testing';

import { ConditionGroup } from '../../../../../core/models/decision-table.model';
import { CDT_ROUTE_CONTINUE_COPY } from '../../cdt.constants';
import {
    RouteCodeCellParams,
    RouteCodeCellRendererComponent,
    routeCodeCellStatus,
} from './route-code-cell-renderer.component';

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

function params(data: ConditionGroup, routeHasTarget = false): RouteCodeCellParams {
    return { value: data.route_code, data, routeHasTarget: () => routeHasTarget } as unknown as RouteCodeCellParams;
}

/** The sprite symbol the status icon points at, e.g. `#icon-thin-warning`. */
function renderedIcon(element: HTMLElement): string | null {
    return element.querySelector('.cdt-route-code-cell__status use')?.getAttribute('href') ?? null;
}

function renderedIconBox(element: HTMLElement): { width: string; height: string } | null {
    const svg = element.querySelector<SVGElement>('.cdt-route-code-cell__status svg');
    return svg ? { width: svg.style.width, height: svg.style.height } : null;
}

function codeElement(element: HTMLElement): Element | null {
    return element.querySelector('.cdt-route-code-cell__code');
}

function render(data: ConditionGroup, routeHasTarget = false): ComponentFixture<RouteCodeCellRendererComponent> {
    const fixture = TestBed.createComponent(RouteCodeCellRendererComponent);
    fixture.componentInstance.agInit(params(data, routeHasTarget));
    fixture.detectChanges();
    return fixture;
}

describe('routeCodeCellStatus', () => {
    it('flags an unwired route code with Continue as ignored', () => {
        expect(routeCodeCellStatus(row({ route_code: 'approve', continue_flag: true }), false)).toEqual({
            kind: 'route-ignored',
            icon: 'thin-warning',
            message: CDT_ROUTE_CONTINUE_COPY.routeCodeIgnored,
            iconWidth: '16px',
            iconHeight: '14px',
        });
    });

    it('flags a wired route code with Continue as a conflict', () => {
        expect(routeCodeCellStatus(row({ route_code: 'approve', continue_flag: true }), true)).toEqual({
            kind: 'conflict',
            icon: 'alert-triangle',
            message: CDT_ROUTE_CONTINUE_COPY.routeContinueConflict,
            iconWidth: '16px',
            iconHeight: '16px',
        });
    });

    it('reads the legacy continue key', () => {
        expect(routeCodeCellStatus(row({ route_code: 'approve', continue: true }), false)?.kind).toBe('route-ignored');
        expect(routeCodeCellStatus(row({ route_code: '', continue: true }), false)).toBeNull();
    });

    it('leaves a row with neither to the red cell border', () => {
        expect(routeCodeCellStatus(row({ route_code: '', continue_flag: false }), false)).toBeNull();
        expect(routeCodeCellStatus(row({ route_code: '   ', continue_flag: false }), false)).toBeNull();
    });

    it('has nothing to say about a missing row', () => {
        expect(routeCodeCellStatus(undefined, false)).toBeNull();
    });

    it('has nothing to say about a row that uses exactly one', () => {
        expect(routeCodeCellStatus(row({ route_code: 'approve', continue_flag: false }), false)).toBeNull();
        expect(routeCodeCellStatus(row({ route_code: 'approve', continue_flag: false }), true)).toBeNull();
        expect(routeCodeCellStatus(row({ route_code: '', continue_flag: true }), false)).toBeNull();
    });
});

describe('RouteCodeCellRendererComponent', () => {
    it('shows the code, not dimmed, and no icon on a valid row', () => {
        const element: HTMLElement = render(row({ route_code: 'approve', continue_flag: false })).nativeElement;

        expect(codeElement(element)?.textContent).toBe('approve');
        expect(codeElement(element)?.classList).not.toContain('cdt-route-code-cell__code--ignored');
        expect(element.querySelector('.cdt-route-code-cell__status')).toBeNull();
    });

    it('shows no icon on a row with neither', () => {
        const element: HTMLElement = render(row({ route_code: '', continue_flag: false })).nativeElement;

        expect(element.querySelector('.cdt-route-code-cell__status')).toBeNull();
    });

    it('dims the code and shows the 16 x 14 thin warning icon when the route code is ignored', () => {
        const element: HTMLElement = render(row({ route_code: 'approve', continue_flag: true })).nativeElement;
        const status = element.querySelector('.cdt-route-code-cell__status');

        expect(codeElement(element)?.classList).toContain('cdt-route-code-cell__code--ignored');
        expect(status?.getAttribute('role')).toBe('img');
        expect(status?.getAttribute('aria-label')).toBe(CDT_ROUTE_CONTINUE_COPY.routeCodeIgnored);
        expect(status?.classList).not.toContain('cdt-route-code-cell__status--conflict');
        expect(renderedIcon(element)).toBe('#icon-thin-warning');
        expect(renderedIconBox(element)).toEqual({ width: '16px', height: '14px' });
    });

    it('shows the conflict icon, without dimming, when a wired route code has Continue', () => {
        const element: HTMLElement = render(row({ route_code: 'approve', continue_flag: true }), true).nativeElement;
        const status = element.querySelector('.cdt-route-code-cell__status');

        expect(codeElement(element)?.classList).not.toContain('cdt-route-code-cell__code--ignored');
        expect(status?.classList).toContain('cdt-route-code-cell__status--conflict');
        expect(status?.getAttribute('aria-label')).toBe(CDT_ROUTE_CONTINUE_COPY.routeContinueConflict);
        expect(renderedIcon(element)).toBe('#icon-alert-triangle');
    });

    it('updates on refresh, as refreshCells does after a Continue change', () => {
        const fixture = render(row({ route_code: 'approve', continue_flag: true }));
        const element = fixture.nativeElement as HTMLElement;
        expect(element.querySelector('.cdt-route-code-cell__status')).not.toBeNull();

        expect(fixture.componentInstance.refresh(params(row({ route_code: 'approve', continue_flag: false })))).toBe(
            true
        );
        fixture.detectChanges();

        expect(element.querySelector('.cdt-route-code-cell__status')).toBeNull();
        expect(codeElement(element)?.classList).not.toContain('cdt-route-code-cell__code--ignored');
    });

    it('updates on refresh when the route code loses its connection', () => {
        const data = row({ route_code: 'approve', continue_flag: true });
        const fixture = render(data, true);
        const element = fixture.nativeElement as HTMLElement;
        expect(renderedIcon(element)).toBe('#icon-alert-triangle');

        fixture.componentInstance.refresh(params(data, false));
        fixture.detectChanges();

        expect(renderedIcon(element)).toBe('#icon-thin-warning');
        expect(codeElement(element)?.classList).toContain('cdt-route-code-cell__code--ignored');
    });
});
