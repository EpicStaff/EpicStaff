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
    'plugin_uninstalled',
    'plugin_reinstalled',
    'plugin_purge_started',
    'plugin_removal_failed',
    'plugin_removal_retried',
    'plugin_purged',
    'grant_purge_started',
    'grant_purged',
    'org_removed_hook_succeeded',
    'org_removed_hook_failed',
    'org_removed_hook_retried',
    'org_removed_hook_skipped',
    'plugin_upgrade_started',
    'plugin_maintenance_started',
    'plugin_upgrade_failed',
    'plugin_upgrade_retried',
    'plugin_upgrade_cancelled',
    'plugin_upgraded',
    'database_backed_up',
    'database_restore_requested',
    'database_restored',
    'database_restore_failed',
    'upgrade_hook_succeeded',
    'upgrade_hook_failed',
    'upgrade_hook_retried',
    'development_target_set',
    'development_target_cleared',
    'development_runtime_file_issued',
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

    it('labels every action it knows, and no other', () => {
        expect(Object.keys(PLUGIN_ACTIVITY_ACTION_LABELS).sort()).toEqual([...EVERY_ACTION].sort());
    });

    it('says what a SuperAdmin did to development: the ports, the keys stopped, the organizations of a file', () => {
        const superAdmin = { kind: 'superadmin', label: 'sam@example.com' } as const;
        render([
            platformEvent({
                id: 1,
                actor: superAdmin,
                action: 'development_target_set',
                detail: { backend_port: 8001, spa_port: 5173 },
            }),
            platformEvent({
                id: 2,
                actor: superAdmin,
                action: 'development_target_set',
                detail: { backend_port: null, spa_port: 5173 },
            }),
            platformEvent({
                id: 3,
                actor: superAdmin,
                action: 'development_target_cleared',
                detail: { revoked_keys: 2 },
            }),
            platformEvent({
                id: 4,
                actor: superAdmin,
                action: 'development_target_cleared',
                detail: { revoked_keys: 0 },
            }),
            platformEvent({
                id: 5,
                actor: superAdmin,
                action: 'development_runtime_file_issued',
                detail: { organizations: 1 },
            }),
        ]);

        expect([0, 1, 2, 3, 4].map((index) => row(index)['Action'])).toEqual([
            'Development started or changed',
            'Development started or changed',
            'Development stopped',
            'Development stopped',
            'Development runtime file downloaded',
        ]);
        expect(details(0)).toEqual(['Backend port 8001 · Frontend dev server port 5173']);
        expect(details(1)).toEqual(['Frontend dev server port 5173']);
        expect(details(2)).toEqual(['2 development keys stopped']);
        expect(details(3)).toEqual([]);
        expect(details(4)).toEqual(['For 1 organization']);
        expect(row(0)['Actor']).toBe('sam@example.com (SuperAdmin)');
    });

    it('marks an API request a development backend made, and no other request', () => {
        render([
            buildPluginActivityEvent({ id: 1, detail: { created_count: 0, development: true } }),
            buildPluginActivityEvent({ id: 2 }),
            platformEvent({ id: 3, action: 'restarted', detail: { development: true } }),
        ]);

        const chips = (index: number): string[] =>
            Array.from(
                element.querySelectorAll('.table-body .table-row')[index].querySelectorAll('.activity__development')
            ).map((chip) => chip.textContent?.trim() ?? '');
        expect(chips(0)).toEqual(['Development']);
        expect(chips(1)).toEqual([]);
        expect(chips(2)).toEqual([]);
        expect(row(0)['Actor']).toBe('Weather (plugin) on behalf of ada@example.com');
        expect(element.querySelector('.activity__request-line code')?.textContent).toBe('POST /api/run-session/ (201)');
    });

    it('shows why a deletion began, by a SuperAdmin or the platform', () => {
        render([
            platformEvent({
                id: 1,
                actor: { kind: 'superadmin', label: 'sam@example.com' },
                organization: { id: 3, name: 'Acme' },
                action: 'grant_purge_started',
                detail: { reason: 'requested', previous_state: 'active', owned_resources: 4 },
            }),
            platformEvent({
                id: 2,
                organization: { id: 4, name: 'Bravo' },
                action: 'grant_purge_started',
                detail: { reason: 'grace_period_over', previous_state: 'suspended', owned_resources: 1 },
            }),
            platformEvent({ id: 3, action: 'plugin_purge_started', detail: { reason: 'plugin_deleted' } }),
            platformEvent({ id: 4, action: 'plugin_purge_started', detail: { reason: 'operator_cleanup' } }),
            platformEvent({ id: 5, action: 'grant_purged', detail: {} }),
        ]);

        expect(row(0)['Action']).toBe('Data deletion started');
        expect(row(0)['Actor']).toBe('sam@example.com (SuperAdmin)');
        expect(details(0)).toEqual(['Reason: Requested']);
        expect(row(1)['Actor']).toBe('Platform');
        expect(details(1)).toEqual(['Reason: Grace period over']);
        expect(row(2)['Action']).toBe('Deletion started');
        expect(details(2)).toEqual(['Reason: Plugin deleted']);
        expect(details(3)).toEqual(['Reason: operator_cleanup']);
        expect(row(4)['Action']).toBe('Data deleted');
        expect(details(4)).toEqual([]);
    });

    it("shows why a data removal or the node's removal failed", () => {
        render([
            platformEvent({
                id: 1,
                organization: { id: 9, name: null },
                action: 'org_removed_hook_failed',
                detail: { job_id: 31, attempt: 9, error: 'Weather answered 500: database is locked' },
            }),
            platformEvent({ id: 2, action: 'plugin_removal_failed', detail: { error: 'conflict: marker mismatch' } }),
            platformEvent({ id: 3, action: 'org_removed_hook_succeeded', detail: { job_id: 32, attempt: 1 } }),
        ]);

        expect(row(0)['Action']).toBe('Data removal failed');
        expect(details(0)).toEqual(['Weather answered 500: database is locked']);
        expect(row(1)['Action']).toBe('Removal from the node failed');
        expect(details(1)).toEqual(['conflict: marker mismatch']);
        expect(row(2)['Action']).toBe('Data removal done');
        expect(details(2)).toEqual([]);
    });

    it('names a deleted organization by its id', () => {
        render([platformEvent({ organization: { id: 9, name: null }, action: 'org_removed_hook_succeeded' })], {
            showOrganization: true,
        });

        expect(row(0)['Organization']).toBe('Organization #9 (deleted)');
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
        expect(row(2)['Organization']).toBe('Organization #9 (deleted)');
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

    it('says what an upgrade changed: the versions, the backups and restores, and each organization', () => {
        render([
            platformEvent({
                id: 1,
                actor: { kind: 'superadmin', label: 'sam@example.com' },
                action: 'plugin_upgrade_started',
                detail: {
                    from_version: '0.6.0',
                    to_version: '0.7.2',
                    access_growth_acknowledged: true,
                    untrusted_acknowledged: false,
                    replaced_version: '0.7.1',
                },
            }),
            platformEvent({
                id: 2,
                action: 'plugin_maintenance_started',
                detail: { to_version: '0.7.0', organizations: 2 },
            }),
            platformEvent({
                id: 3,
                action: 'database_backed_up',
                detail: { file_name: 'x.dump', reason: 'pre_upgrade', size_bytes: 2048, version: '0.6.0' },
            }),
            platformEvent({
                id: 4,
                action: 'plugin_upgrade_failed',
                detail: { to_version: '0.7.1', stage: 'migrating', step: 'migrate', error: '005_broken.sql line 1' },
            }),
            platformEvent({
                id: 5,
                action: 'plugin_upgraded',
                detail: { from_version: '0.6.0', to_version: '0.7.0', maintenance_seconds: 95 },
            }),
            platformEvent({
                id: 6,
                organization: { id: 3, name: 'Acme' },
                action: 'upgrade_hook_succeeded',
                detail: { job_id: 40, attempt: 1, from_version: '0.6.0', to_version: '0.7.0' },
            }),
            platformEvent({
                id: 7,
                organization: { id: 4, name: 'Bravo' },
                action: 'upgrade_hook_failed',
                detail: { job_id: 41, attempt: 3, error: 'Weather answered HTTP 500.', next_attempt_at: null },
            }),
            platformEvent({
                id: 8,
                action: 'database_restored',
                detail: { file_name: '20261021T110100Z-u8-pre_upgrade.dump', pre_restore_file_name: 'y.dump' },
            }),
            platformEvent({
                id: 9,
                action: 'database_restore_failed',
                detail: { step: 'recreate', error: 'disk full' },
            }),
        ]);

        expect(row(0)['Action']).toBe('Upgrade started');
        expect(details(0)).toEqual(['0.6.0 → 0.7.2 · replaces 0.7.1']);
        expect(details(1)).toEqual(['To 0.7.0 · 2 organizations offline']);
        expect(details(2)).toEqual(['Before upgrade · holds 0.6.0 · 2 KB']);
        expect(row(3)['Action']).toBe('Upgrade failed');
        expect(details(3)).toEqual(['To 0.7.1 · while running migrations', '005_broken.sql line 1']);
        expect(details(4)).toEqual(['0.6.0 → 0.7.0 · offline 2 min']);
        expect(row(5)['Action']).toBe('Upgrade hook succeeded');
        expect(details(5)).toEqual(['From 0.6.0 to 0.7.0']);
        expect(details(6)).toEqual(['No retries left: Retry it on its row', 'Weather answered HTTP 500.']);
        expect(details(7)).toEqual(['From 20261021T110100Z-u8-pre_upgrade.dump']);
        expect(details(8)).toEqual(['While recreating the database', 'disk full']);
    });
});
