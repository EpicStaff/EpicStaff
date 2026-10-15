import { signal } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { ActionCode, ResourceCode } from '@shared/models';

import { PermissionsService } from '../../../services/auth/permissions.service';
import { ImportFlowSettingsService } from './import-flow-settings.service';

describe('ImportFlowSettingsService', () => {
    const canUpdateFlows = signal(false);
    let service: ImportFlowSettingsService;

    beforeEach(() => {
        localStorage.clear();
        canUpdateFlows.set(false);
        const permissions = {
            can: (resource: ResourceCode, action: ActionCode) =>
                resource === ResourceCode.Flows && action === ActionCode.Update && canUpdateFlows(),
        };

        TestBed.configureTestingModule({
            providers: [{ provide: PermissionsService, useValue: permissions as unknown as PermissionsService }],
        });
        service = TestBed.inject(ImportFlowSettingsService);
        service.update({ preserveUuids: true, replaceExisting: true });
    });

    it('drops replaceExisting from the request when the user cannot update flows', () => {
        expect(service.settings().replaceExisting).toBe(true);
        expect(service.requestSettings().replaceExisting).toBe(false);
    });

    it('drops replaceExisting from the request when preserveUuids is off', () => {
        canUpdateFlows.set(true);
        service.update({ preserveUuids: false });

        expect(service.settings().replaceExisting).toBe(true);
        expect(service.requestSettings().replaceExisting).toBe(false);
    });

    it('sends replaceExisting once flow update permission is granted', () => {
        canUpdateFlows.set(true);

        expect(service.requestSettings()).toEqual({
            preserveUuids: true,
            replaceExisting: true,
            importLabels: true,
        });
    });
});
