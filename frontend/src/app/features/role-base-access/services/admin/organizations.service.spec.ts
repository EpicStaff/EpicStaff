import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { OrganizationDeleteReport } from '@shared/models';

import { ConfigService } from '../../../../services/config';
import { AdminOrganizationsService } from './organizations.service';

const REPORT: OrganizationDeleteReport = { organization_id: 7, affected_resources: {} };

describe('AdminOrganizationsService.deleteOrganization', () => {
    let service: AdminOrganizationsService;
    let httpMock: HttpTestingController;

    beforeEach(() => {
        TestBed.configureTestingModule({
            providers: [
                provideHttpClient(),
                provideHttpClientTesting(),
                { provide: ConfigService, useValue: { apiUrl: '/api/' } as unknown as ConfigService },
            ],
        });
        service = TestBed.inject(AdminOrganizationsService);
        httpMock = TestBed.inject(HttpTestingController);
    });

    afterEach(() => httpMock.verify());

    it('sends a dry run without a body', () => {
        service.deleteOrganization(7, true).subscribe();

        const request = httpMock.expectOne('/api/admin/organizations/7/?dry_run=true');
        expect(request.request.method).toBe('DELETE');
        expect(request.request.body).toBeNull();
        request.flush(REPORT);
    });

    it('sends the verification phrase in the body of the real delete', () => {
        service.deleteOrganization(7, false, 'delete-Acme').subscribe();

        const request = httpMock.expectOne('/api/admin/organizations/7/?dry_run=false');
        expect(request.request.method).toBe('DELETE');
        expect(request.request.body).toEqual({ verification_phrase: 'delete-Acme' });
        request.flush(REPORT);
    });
});
