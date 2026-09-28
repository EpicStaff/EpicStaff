import { TestBed } from '@angular/core/testing';
import { OrganizationDeleteReport } from '@shared/models';
import { firstValueFrom, of } from 'rxjs';

import { AdminOrganizationsService } from './organizations.service';
import { OrganizationsStorageService } from './organizations-storage.service';

const REPORT: OrganizationDeleteReport = { organization_id: 7, affected_resources: {} };

describe('OrganizationsStorageService.deleteOrganization', () => {
    let storage: OrganizationsStorageService;
    let apiService: { deleteOrganization: ReturnType<typeof vi.fn> };

    beforeEach(() => {
        apiService = { deleteOrganization: vi.fn(() => of(REPORT)) };
        TestBed.configureTestingModule({
            providers: [
                { provide: AdminOrganizationsService, useValue: apiService as unknown as AdminOrganizationsService },
            ],
        });
        storage = TestBed.inject(OrganizationsStorageService);
    });

    it('forwards the verification phrase to the API service', async () => {
        await firstValueFrom(storage.deleteOrganization(7, false, 'delete-Acme'));

        expect(apiService.deleteOrganization).toHaveBeenCalledWith(7, false, 'delete-Acme');
    });

    it('forwards no phrase for a dry run', async () => {
        await firstValueFrom(storage.deleteOrganization(7, true));

        expect(apiService.deleteOrganization).toHaveBeenCalledWith(7, true, undefined);
    });
});
