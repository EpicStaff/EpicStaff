import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { ActionCode } from '@shared/models';
import {
    ROLE_PERMISSION_EXTENSIONS,
    RolePermissionExtensionError,
    RolePermissionExtensionRoleState,
    RolePermissionExtensionRow,
} from '@shared/services';
import { of } from 'rxjs';

import { ActiveOrgService } from '../../../services/auth/active-org.service';
import { ConfigService } from '../../../services/config';
import { providePluginsExtensions } from '../plugins.providers';
import { AvailablePluginsStorageService } from '../services/available-plugins-storage.service';
import { buildPluginRolePermissions, buildPluginRoleRow } from '../testing/plugin-fixtures';
import { PluginRolePermissionExtension } from './plugin-role-permission-extension';

const BASE_URL = '/api/admin/plugin-role-permissions/';

describe('PluginRolePermissionExtension', () => {
    let extension: PluginRolePermissionExtension;
    let http: HttpTestingController;
    let config: { apiUrl: string; isPluginsEnabled: boolean };
    const availablePlugins = { refresh: vi.fn(() => of([])) };

    beforeEach(() => {
        vi.clearAllMocks();
        config = { apiUrl: '/api/', isPluginsEnabled: true };
        TestBed.configureTestingModule({
            providers: [
                provideHttpClient(),
                provideHttpClientTesting(),
                providePluginsExtensions(),
                { provide: ConfigService, useValue: config },
                { provide: AvailablePluginsStorageService, useValue: availablePlugins },
            ],
        });
        TestBed.inject(ActiveOrgService).set(1);
        extension = TestBed.inject(PluginRolePermissionExtension);
        http = TestBed.inject(HttpTestingController);
    });

    afterEach(() => {
        http.verify();
        localStorage.clear();
    });

    it('is registered as a Roles-matrix extension and is inactive while the plugin platform is off', () => {
        expect(TestBed.inject(ROLE_PERMISSION_EXTENSIONS)).toEqual([extension]);
        expect(extension.groupKey).toBe('plugins');
        expect(extension.groupLabel).toBe('Plugins');
        expect(extension.superadminRoleNote).toBe('Superadmins open plugins through their role in an organization.');
        expect(extension.isActive()).toBe(true);

        config.isPluginsEnabled = false;

        expect(extension.isActive()).toBe(false);
    });

    it('maps the rows of an organization to matrix rows: code, cells, tooltips, View suggested, ceiling', () => {
        let rows: RolePermissionExtensionRow[] = [];
        extension.rowsForOrg(3).subscribe((result) => (rows = result));

        const request = http.expectOne(`${BASE_URL}rows/?org_id=3`);
        expect(request.request.method).toBe('GET');
        request.flush({ organization: { id: 3, name: 'Org C' }, rows: [buildPluginRoleRow()] });

        expect(rows).toEqual([
            {
                code: 'plugin:weather',
                label: 'Weather',
                description: '',
                iconUrl: '/api/plugin-public/weather/icon/?v=0.2.0',
                actions: [
                    { action: ActionCode.Read, description: 'Open Weather and see forecasts.', requires: [] },
                    {
                        action: ActionCode.Update,
                        description: 'Change the places Weather forecasts.',
                        requires: [ActionCode.Read],
                    },
                ],
                grantable: [ActionCode.Read],
            },
        ]);
    });

    it("reads a built-in role's rows without an organization, and a given one as org_id", () => {
        const states: RolePermissionExtensionRoleState[] = [];
        extension.roleState(2).subscribe((state) => states.push(state));
        http.expectOne(`${BASE_URL}2/`).flush(
            buildPluginRolePermissions({
                role: { id: 2, name: 'Member', is_built_in: true, org_id: null },
                organization: null,
                editable: false,
                rows: [{ ...buildPluginRoleRow({ ceiling: [] }), granted: ['read'] }],
            })
        );
        extension.roleState(2, 5).subscribe((state) => states.push(state));
        http.expectOne(`${BASE_URL}2/?org_id=5`).flush(buildPluginRolePermissions({ editable: false }));

        expect(states[0].editable).toBe(false);
        expect(states[0].granted).toEqual([{ code: 'plugin:weather', actions: [ActionCode.Read] }]);
        expect(states[0].rows[0].grantable).toEqual([]);
        expect(states).toHaveLength(2);
    });

    it('sends the selections back as the PUT body, leaving out codes and actions that are not a plugin’s', () => {
        let saved: RolePermissionExtensionRoleState | undefined;
        extension
            .saveRole(7, [
                { code: 'plugin:weather', actions: [ActionCode.Read, ActionCode.Update] },
                { code: 'plugin:atlas', actions: [] },
                { code: 'flows', actions: [ActionCode.Read] },
                { code: 'plugin:clock', actions: [ActionCode.List, ActionCode.Read] },
            ])
            .subscribe((state) => (saved = state));

        const request = http.expectOne(`${BASE_URL}7/`);
        expect(request.request.method).toBe('PUT');
        expect(request.request.body).toEqual({
            plugins: [
                { plugin_identifier: 'weather', actions: ['read', 'update'] },
                { plugin_identifier: 'atlas', actions: [] },
                { plugin_identifier: 'clock', actions: ['read'] },
            ],
        });
        request.flush(buildPluginRolePermissions({ rows: [{ ...buildPluginRoleRow(), granted: ['read', 'update'] }] }));

        expect(saved?.granted).toEqual([{ code: 'plugin:weather', actions: [ActionCode.Read, ActionCode.Update] }]);
    });

    it('refreshes the left bar only when the saved role belongs to the active organization', () => {
        extension.saveRole(7, []).subscribe();
        http.expectOne(`${BASE_URL}7/`).flush(buildPluginRolePermissions());
        expect(availablePlugins.refresh).toHaveBeenCalledTimes(1);

        extension.saveRole(8, []).subscribe();
        http.expectOne(`${BASE_URL}8/`).flush(
            buildPluginRolePermissions({ role: { id: 8, name: 'Other', is_built_in: false, org_id: 2 } })
        );
        expect(availablePlugins.refresh).toHaveBeenCalledTimes(1);
    });

    it.each([
        ['permission_escalation_denied', 403, "You can't give plugin permissions you don't have yourself"],
        ['built_in_role_immutable', 403, "Built-in roles get their plugin permissions from each plugin's defaults"],
        ['role_not_found', 404, 'This role no longer exists, or you can no longer see it.'],
    ])('fails with a message ready to show for %s', (code, status, message) => {
        let failure: unknown;
        extension.saveRole(7, []).subscribe({ error: (error: unknown) => (failure = error) });

        http.expectOne(`${BASE_URL}7/`).flush(
            { status_code: status, code, message: 'server' },
            {
                status,
                statusText: 'Refused',
            }
        );

        expect(failure).toBeInstanceOf(RolePermissionExtensionError);
        expect((failure as RolePermissionExtensionError).message).toContain(message);
    });

    it('names the refused plugin of invalid_plugin_role_permissions by its name, found by the index of the body', () => {
        extension.rowsForOrg(1).subscribe();
        http.expectOne(`${BASE_URL}rows/?org_id=1`).flush({
            organization: { id: 1, name: 'Org A' },
            rows: [buildPluginRoleRow(), buildPluginRoleRow({ plugin_identifier: 'atlas', name: 'Atlas Maps' })],
        });
        let failure: unknown;
        extension
            .saveRole(7, [
                { code: 'plugin:weather', actions: [ActionCode.Read] },
                { code: 'plugin:atlas', actions: [ActionCode.Update] },
            ])
            .subscribe({ error: (error: unknown) => (failure = error) });

        http.expectOne(`${BASE_URL}7/`).flush(
            {
                status_code: 400,
                code: 'invalid_plugin_role_permissions',
                message: 'Invalid.',
                errors: [{ loc: 'plugins[1].actions', message: 'Edit needs View.' }],
            },
            { status: 400, statusText: 'Bad Request' }
        );

        expect((failure as RolePermissionExtensionError).message).toBe(
            "Some plugin permissions can't be saved. Atlas Maps: Edit needs View."
        );
    });

    it('fails a load with its fallback message when the server sends no known code', () => {
        let failure: unknown;
        extension.rowsForOrg(1).subscribe({ error: (error: unknown) => (failure = error) });

        http.expectOne(`${BASE_URL}rows/?org_id=1`).flush('Bad gateway', { status: 502, statusText: 'Bad Gateway' });

        expect((failure as RolePermissionExtensionError).message).toBe("Couldn't load the plugin permissions.");
    });
});
