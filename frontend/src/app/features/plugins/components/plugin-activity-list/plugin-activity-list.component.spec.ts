import { ComponentFixture, TestBed } from '@angular/core/testing';

import { PluginActivityAction, PluginActivityEvent } from '../../models/plugin-activity.model';
import { buildPluginActivityEvent } from '../../testing/plugin-fixtures';
import { PLUGIN_ACTIVITY_ACTION_LABELS } from '../../utils/plugin-activity-display.util';
import { PluginActivityListComponent } from './plugin-activity-list.component';

class ResizeObserverStub {
    observe(): void {}
    unobserve(): void {}
    disconnect(): void {}
}

const EVERY_ACTION: PluginActivityAction[] = [
    'api_request',
    'package_approved',
    'grant_created',
    'install_hook_succeeded',
    'install_hook_failed',
    'install_hook_retried',
    'settings_changed',
    'limits_changed',
    'restarted',
    'grant_suspended',
    'grant_resumed',
    'database_ready',
    'database_failed',
    'database_limit_restored',
];

/** A deployment-wide event of the platform, without a request or a target. */
function platformEvent(overrides: Partial<PluginActivityEvent>): PluginActivityEvent {
    return buildPluginActivityEvent({
        organization: null,
        actor: { kind: 'platform', label: 'EpicStaff' },
        on_behalf_of: null,
        request: null,
        target: null,
        detail: {},
        ...overrides,
    });
}

describe('PluginActivityListComponent', () => {
    let fixture: ComponentFixture<PluginActivityListComponent>;
    let element: HTMLElement;

    function render(events: PluginActivityEvent[], inputs: Record<string, unknown> = {}): void {
        fixture = TestBed.createComponent(PluginActivityListComponent);
        element = fixture.nativeElement as HTMLElement;
        fixture.componentRef.setInput('events', events);
        for (const [name, value] of Object.entries(inputs)) fixture.componentRef.setInput(name, value);
        fixture.detectChanges();
    }

    function headers(): string[] {
        return Array.from(element.querySelectorAll('.table-header .table-cell')).map(
            (cell) => cell.textContent?.trim() ?? ''
        );
    }

    /** The text of each cell of the row at `index`, keyed by its column header. */
    function row(index: number): Record<string, string> {
        const cells = Array.from(
            element.querySelectorAll('.table-body .table-row')[index].querySelectorAll('.table-cell')
        );
        const labels = headers();
        return Object.fromEntries(
            cells.map((cell, column) => [labels[column], cell.textContent?.replace(/\s+/g, ' ').trim() ?? ''])
        );
    }

    /** The lines of the Details cell of the row at `index`: request line, target, error. */
    function details(index: number): string[] {
        const tableRow = element.querySelectorAll('.table-body .table-row')[index];
        return Array.from(tableRow.querySelectorAll('.activity__details > *')).map(
            (line) => line.textContent?.trim() ?? ''
        );
    }

    beforeEach(() => {
        vi.stubGlobal('ResizeObserver', ResizeObserverStub);
        TestBed.configureTestingModule({ imports: [PluginActivityListComponent] });
    });

    afterEach(() => vi.unstubAllGlobals());

    it('names who acted: the plugin on behalf of a person, the plugin alone, a SuperAdmin, the platform', () => {
        render([
            buildPluginActivityEvent({ id: 1 }),
            buildPluginActivityEvent({ id: 2, on_behalf_of: null }),
            buildPluginActivityEvent({
                id: 3,
                actor: { kind: 'superadmin', label: 'sam@example.com' },
                on_behalf_of: null,
                action: 'grant_created',
                request: null,
                target: null,
            }),
            buildPluginActivityEvent({
                id: 4,
                actor: { kind: 'platform', label: 'EpicStaff' },
                on_behalf_of: null,
                action: 'install_hook_succeeded',
                request: null,
                target: null,
            }),
        ]);

        expect(row(0)['Actor']).toBe('Weather (plugin) on behalf of ada@example.com');
        expect(row(1)['Actor']).toBe('Weather (plugin)');
        expect(row(2)['Actor']).toBe('sam@example.com (SuperAdmin)');
        expect(row(3)['Actor']).toBe('Platform');
    });

    it('shows the request line and the target of an API request', () => {
        render([buildPluginActivityEvent()]);

        expect(details(0)).toEqual(['POST /api/run-session/ (201)', 'Weather forecast']);
        expect(row(0)['Action']).toBe('API request');
    });

    it("falls back to the target's type and id, and shows a failed install's error", () => {
        render([
            buildPluginActivityEvent({ id: 1, target: { resource_type: 'secrets', id: '9', label: null } }),
            buildPluginActivityEvent({
                id: 2,
                actor: { kind: 'platform', label: 'EpicStaff' },
                on_behalf_of: null,
                action: 'install_hook_failed',
                request: null,
                target: null,
                detail: { job_id: 3, attempt: 1, error: 'EpicStaff answered 403' },
            }),
        ]);

        expect(details(0)).toEqual(['POST /api/run-session/ (201)', 'secrets 9']);
        expect(details(1)).toEqual(['EpicStaff answered 403']);
    });

    it.each(EVERY_ACTION)('labels the action %s', (action) => {
        render([buildPluginActivityEvent({ action })]);

        expect(row(0)['Action']).toBe(PLUGIN_ACTIVITY_ACTION_LABELS[action]);
        expect(row(0)['Action']).not.toBe(action);
    });

    it('says a SuperAdmin suspended or resumed the plugin in the organization', () => {
        const bySam = { kind: 'superadmin' as const, label: 'sam@example.com' };
        render([
            buildPluginActivityEvent({
                id: 1,
                actor: bySam,
                on_behalf_of: null,
                action: 'grant_suspended',
                request: null,
                target: null,
                detail: { previous_state: 'active', purge_after: '2026-11-20T09:00:00Z' },
            }),
            buildPluginActivityEvent({
                id: 2,
                actor: bySam,
                on_behalf_of: null,
                action: 'grant_resumed',
                request: null,
                target: null,
                detail: { state: 'active' },
            }),
        ]);

        expect(row(0)['Action']).toBe('Suspended in this organization');
        expect(row(0)['Actor']).toBe('sam@example.com (SuperAdmin)');
        expect(row(1)['Action']).toBe('Resumed in this organization');
    });

    it('names the database events, by the platform, and shows why a database setup failed', () => {
        render([
            platformEvent({ id: 1, action: 'database_ready', detail: { migrations_applied: 1 } }),
            platformEvent({
                id: 2,
                action: 'database_failed',
                detail: { error: 'Migration 001_weather.sql failed: syntax error' },
            }),
            platformEvent({ id: 3, action: 'database_limit_restored', detail: { setting: 'statement_timeout' } }),
        ]);

        expect([row(0)['Action'], row(1)['Action'], row(2)['Action']]).toEqual([
            'Database ready',
            'Database setup failed',
            'Database timeout restored',
        ]);
        expect(row(0)['Actor']).toBe('Platform');
        expect(details(0)).toEqual([]);
        expect(details(1)).toEqual(['Migration 001_weather.sql failed: syntax error']);
        expect(details(2)).toEqual([]);
    });

    it('shows the overrides a limits change left in force, as the limits form names them', () => {
        const bySam = { kind: 'superadmin' as const, label: 'sam@example.com' };
        render([
            platformEvent({
                id: 1,
                actor: bySam,
                action: 'limits_changed',
                detail: { memory_mb: 128, db_connections: 2, statement_timeout_seconds: 5, cpu_priority: 'low' },
            }),
            platformEvent({ id: 2, actor: bySam, action: 'limits_changed', detail: {} }),
            platformEvent({ id: 3, actor: bySam, action: 'limits_changed', detail: { disk_mb: 64 } }),
        ]);

        expect(details(0)).toEqual([
            'Overrides: Memory 128 MB, Database connections 2, Statement timeout 5 s, CPU priority Low',
        ]);
        expect(details(1)).toEqual(['Overrides: none']);
        expect(details(2)).toEqual(['Overrides: disk_mb 64']);
    });

    it('shows the organization and plugin columns only when asked', () => {
        const events = [
            buildPluginActivityEvent({ id: 1 }),
            buildPluginActivityEvent({
                id: 2,
                organization: null,
                actor: { kind: 'superadmin', label: 'sam@example.com' },
                action: 'package_approved',
            }),
            buildPluginActivityEvent({
                id: 3,
                organization: { id: 9, name: null },
                plugin: { identifier: 'gone', name: null },
            }),
        ];
        render(events);
        expect(headers()).toEqual(['When', 'Actor', 'Action', 'Details']);

        render(events, { showOrganization: true, showPlugin: true });
        expect(headers()).toEqual(['When', 'Plugin', 'Organization', 'Actor', 'Action', 'Details']);
        expect(row(0)['Organization']).toBe('Acme');
        expect(row(1)['Organization']).toBe('Whole deployment');
        expect(row(2)['Organization']).toBe('Organization 9');
        expect(row(0)['Plugin']).toBe('Weather');
        expect(row(2)['Plugin']).toBe('gone');
    });

    it('shows when it happened relative to now', () => {
        render([buildPluginActivityEvent({ created_at: new Date(Date.now() - 3 * 3_600_000).toISOString() })]);

        expect(row(0)['When']).toBe('3h ago');
    });

    it('says when there is nothing, and waits while loading', () => {
        render([], { emptyMessage: 'Nothing here yet.' });
        expect(element.textContent).toContain('Nothing here yet.');

        render([], { isLoading: true, emptyMessage: 'Nothing here yet.' });
        expect(element.querySelector('app-loading-spinner')).not.toBeNull();
        expect(element.textContent).not.toContain('Nothing here yet.');
    });

    it('offers pages only when there is more than one, and asks for the one picked', () => {
        render([buildPluginActivityEvent()], { totalCount: 50, pageSize: 50 });
        expect(element.querySelector('app-pagination-controls')).toBeNull();

        const pages: number[] = [];
        render([buildPluginActivityEvent()], { totalCount: 120, pageSize: 50, page: 1 });
        fixture.componentInstance.pageChange.subscribe((page) => pages.push(page));
        const pageTwo = Array.from(element.querySelectorAll<HTMLButtonElement>('app-pagination-controls button')).find(
            (button) => button.textContent?.trim() === '2'
        );
        pageTwo!.click();

        expect(pages).toEqual([2]);
    });
});
