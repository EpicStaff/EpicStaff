import { provideHttpClient } from '@angular/common/http';
import { TestBed } from '@angular/core/testing';
import { ActivatedRouteSnapshot, Router, RouterStateSnapshot, UrlTree } from '@angular/router';
import { ActionCode, ActivePermissions, ResourceCode } from '@shared/models';

import { PermissionsService } from '../../services/auth/permissions.service';
import { permissionGuard } from './workspace.guard';

type Grants = Partial<Record<ResourceCode, ActionCode[]>>;

describe('permissionGuard', () => {
    /** Runs the guard on a route with `data`, for a role holding `grants`; a redirect comes back as its URL. */
    function run(data: Record<string, unknown>, grants: Grants): string | true {
        TestBed.resetTestingModule();
        TestBed.configureTestingModule({ providers: [provideHttpClient()] });
        TestBed.inject(PermissionsService).setActivePermissions({
            org_id: 1,
            is_superadmin: false,
            role: { id: 1, name: 'Custom' },
            permissions: grants as ActivePermissions['permissions'],
        });
        const result = TestBed.runInInjectionContext(() =>
            permissionGuard({ data } as unknown as ActivatedRouteSnapshot, {} as RouterStateSnapshot)
        ) as boolean | UrlTree;
        return result === true ? true : TestBed.inject(Router).serializeUrl(result as UrlTree);
    }

    const agentsOrSurfaces = {
        anyPermission: [
            [ResourceCode.Agents, ActionCode.Read],
            [ResourceCode.Surfaces, ActionCode.Read],
        ],
    };

    it('still checks the single permission', () => {
        const data = { permission: [ResourceCode.Tools, ActionCode.Read] };

        expect(run(data, { [ResourceCode.Tools]: [ActionCode.Read] })).toBe(true);
        expect(run(data, { [ResourceCode.Agents]: [ActionCode.Read] })).toBe('/agents');
    });

    it.each<[string, Grants]>([
        ['Agents READ', { [ResourceCode.Agents]: [ActionCode.Read] }],
        ['Surfaces READ', { [ResourceCode.Surfaces]: [ActionCode.Read] }],
    ])('lets in a role with %s when any of several is enough', (_name, grants) => {
        expect(run(agentsOrSurfaces, grants)).toBe(true);
    });

    it('redirects a role with none of them, and one with only another action on them', () => {
        expect(run(agentsOrSurfaces, { [ResourceCode.Tools]: [ActionCode.Read] })).toBe('/tools');
        expect(run(agentsOrSurfaces, { [ResourceCode.Surfaces]: [ActionCode.Update] })).toBe('/profile');
    });
});
