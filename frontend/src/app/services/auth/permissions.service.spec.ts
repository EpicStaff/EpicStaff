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

describe('PermissionsService files tab', () => {
    it('opens Key-Value Tables for a role that can read only key-value tables', () => {
        const service = serviceWith([ResourceCode.KeyValueTables]);
        expect(service.resolveFilesTab()).toBe('/files/key-value-tables');
        expect(service.resolveDefaultRoute()).toBe('/files/key-value-tables');
    });

    it('prefers Knowledge Sources, then Storage, over Key-Value Tables', () => {
        expect(
            serviceWith([
                ResourceCode.KeyValueTables,
                ResourceCode.Files,
                ResourceCode.KnowledgeSources,
            ]).resolveFilesTab()
        ).toBe('/files/knowledge-sources');
        TestBed.resetTestingModule();
        expect(serviceWith([ResourceCode.KeyValueTables, ResourceCode.Files]).resolveFilesTab()).toBe('/files/storage');
    });

    it('has no Files tab without read on any of them, and falls back to the profile', () => {
        const service = serviceWith([]);
        expect(service.resolveFilesTab()).toBeNull();
        expect(service.resolveDefaultRoute()).toBe('/profile');
    });
});
