import { provideHttpClient } from '@angular/common/http';
import { inject } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { ActivatedRouteSnapshot, provideRouter, Router, RouterStateSnapshot, Routes, UrlTree } from '@angular/router';
import { ActionCode, ActivePermissions, ResourceCode } from '@shared/models';

import { PermissionsService } from '../../../services/auth/permissions.service';
import { LastVisitedTabService } from '../../../services/last-visited-tab.service';
import { FILES_TAB } from '../constants/files-tabs';
import { storageTabGuard } from './storage-tab.guard';

type Grants = Partial<Record<ResourceCode, ActionCode[]>>;

const READ = [ActionCode.Read];

/**
 * The `/storage` route shape of app.routes.ts: an index redirect to the remembered tab, then one guarded route per tab.
 * A hand-kept copy (the real routes need the whole app shell): keep it in step with the `/storage` routes there.
 */
const STORAGE_ROUTES: Routes = [
    { path: 'agents', children: [] },
    {
        path: 'storage',
        children: [
            {
                path: '',
                canActivate: [
                    () => {
                        const last = inject(LastVisitedTabService).get('/storage');
                        const permissions = inject(PermissionsService);
                        return inject(Router).parseUrl(
                            last ?? permissions.resolveStorageTab() ?? permissions.resolveDefaultRoute()
                        );
                    },
                ],
                children: [],
            },
            {
                path: FILES_TAB.KnowledgeSources,
                canActivate: [storageTabGuard],
                data: { permission: [ResourceCode.KnowledgeSources, ActionCode.Read] },
                children: [],
            },
            {
                path: FILES_TAB.Storage,
                canActivate: [storageTabGuard],
                data: { permission: [ResourceCode.Files, ActionCode.Read] },
                children: [],
            },
            {
                path: FILES_TAB.KeyValueTables,
                canActivate: [storageTabGuard],
                data: { permission: [ResourceCode.KeyValueTables, ActionCode.Read] },
                children: [],
            },
        ],
    },
];

describe('storageTabGuard', () => {
    function setUp(grants: Grants): void {
        TestBed.configureTestingModule({ providers: [provideHttpClient(), provideRouter(STORAGE_ROUTES)] });
        TestBed.inject(PermissionsService).setActivePermissions({
            org_id: 1,
            is_superadmin: false,
            role: { id: 1, name: 'Custom' },
            permissions: grants as ActivePermissions['permissions'],
        });
    }

    /** Runs the guard for the Files tab (needs Read on Files) for a role with `grants`. */
    function runOnFilesTab(grants: Grants): string | true {
        setUp(grants);
        const route = {
            data: { permission: [ResourceCode.Files, ActionCode.Read] },
        } as unknown as ActivatedRouteSnapshot;
        const result = TestBed.runInInjectionContext(() => storageTabGuard(route, {} as RouterStateSnapshot)) as
            | boolean
            | UrlTree;
        return result === true ? true : TestBed.inject(Router).serializeUrl(result as UrlTree);
    }

    afterEach(() => localStorage.clear());

    it.each<[string, Grants, string | true]>([
        ['admits a role that reads the tab', { [ResourceCode.Files]: READ }, true],
        [
            'sends a role that cannot read the tab to another readable storage tab',
            { [ResourceCode.Agents]: READ, [ResourceCode.KeyValueTables]: READ },
            '/storage/key-value-tables',
        ],
        ['sends a role that reads no storage tab to the default route', { [ResourceCode.Agents]: READ }, '/agents'],
    ])('%s', (_label, grants, expected) => {
        expect(runOnFilesTab(grants)).toBe(expected);
    });

    it('keeps the caller in Storage when the remembered tab is no longer readable', async () => {
        localStorage.setItem('lastVisitedTab', JSON.stringify({ '/storage': '/storage/files' }));
        setUp({ [ResourceCode.Agents]: READ, [ResourceCode.KnowledgeSources]: READ });
        const router = TestBed.inject(Router);

        await router.navigateByUrl('/storage');

        expect(router.url).toBe('/storage/knowledge-sources');
    });
});
