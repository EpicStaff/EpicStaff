import { provideHttpClient } from '@angular/common/http';
import { TestBed } from '@angular/core/testing';
import { ActionCode, ActivePermissions, ResourceCode } from '@shared/models';

import { ConfigService } from '../config';
import { PermissionsService } from './permissions.service';

function serviceWith(readable: ResourceCode[]): PermissionsService {
    TestBed.configureTestingModule({
        providers: [provideHttpClient(), { provide: ConfigService, useValue: {} }],
    });
    const service = TestBed.inject(PermissionsService);
    const permissions = Object.fromEntries(readable.map((resource) => [resource, [ActionCode.Read]]));
    service.setActivePermissions({
        org_id: 1,
        is_superadmin: false,
        role: { id: 1, name: 'Custom' },
        permissions: permissions as ActivePermissions['permissions'],
    });
    return service;
}

describe('PermissionsService storage tab', () => {
    it('opens Key-Value Tables for a role that can read only key-value tables', () => {
        const service = serviceWith([ResourceCode.KeyValueTables]);
        expect(service.resolveStorageTab()).toBe('/storage/key-value-tables');
        expect(service.resolveDefaultRoute()).toBe('/storage/key-value-tables');
    });

    it('prefers Knowledge Sources, then Files, over Key-Value Tables', () => {
        expect(
            serviceWith([
                ResourceCode.KeyValueTables,
                ResourceCode.Files,
                ResourceCode.KnowledgeSources,
            ]).resolveStorageTab()
        ).toBe('/storage/knowledge-sources');
        TestBed.resetTestingModule();
        expect(serviceWith([ResourceCode.KeyValueTables, ResourceCode.Files]).resolveStorageTab()).toBe(
            '/storage/files'
        );
    });

    it('has no Storage tab without read on any of them, and falls back to the profile', () => {
        const service = serviceWith([]);
        expect(service.resolveStorageTab()).toBeNull();
        expect(service.resolveDefaultRoute()).toBe('/profile');
    });
});

describe('PermissionsService settings access', () => {
    function serviceFor(grants: Partial<Record<ResourceCode, ActionCode[]>>, isPluginsEnabled: boolean) {
        TestBed.configureTestingModule({
            providers: [provideHttpClient(), { provide: ConfigService, useValue: { isPluginsEnabled } }],
        });
        const service = TestBed.inject(PermissionsService);
        service.setActivePermissions({
            org_id: 1,
            is_superadmin: false,
            role: { id: 1, name: 'Custom' },
            permissions: grants as ActivePermissions['permissions'],
        });
        return service;
    }

    it('opens Settings to a role that reads only the audit trail while plugins are on', () => {
        const service = serviceFor({ [ResourceCode.Audit]: [ActionCode.Read] }, true);

        expect(service.canSeePluginActivity()).toBe(true);
        expect(service.canOpenConfigureModelsDialog()).toBe(true);
    });

    it('keeps Settings closed to that role while plugins are off', () => {
        const service = serviceFor({ [ResourceCode.Audit]: [ActionCode.Read] }, false);

        expect(service.canSeePluginActivity()).toBe(false);
        expect(service.canOpenConfigureModelsDialog()).toBe(false);
    });

    it('opens Settings to a settings permission without plugin activity', () => {
        const service = serviceFor({ [ResourceCode.Voice]: [ActionCode.Read] }, true);

        expect(service.canSeePluginActivity()).toBe(false);
        expect(service.canOpenConfigureModelsDialog()).toBe(true);
    });
});
