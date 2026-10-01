import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { UserDeleteReport } from '@shared/models';

import { ConfigService } from '../../../../services/config';
import { AdminUserService } from './admin-user.service';

const REPORT: UserDeleteReport = { user_id: 42, affected_resources: {} };

describe('AdminUserService.deleteUser', () => {
    let service: AdminUserService;
    let httpMock: HttpTestingController;

    beforeEach(() => {
        TestBed.configureTestingModule({
            providers: [
                provideHttpClient(),
                provideHttpClientTesting(),
                { provide: ConfigService, useValue: { apiUrl: '/api/' } as unknown as ConfigService },
            ],
        });
        service = TestBed.inject(AdminUserService);
        httpMock = TestBed.inject(HttpTestingController);
    });

    afterEach(() => httpMock.verify());

    it('sends a dry run without a body', () => {
        service.deleteUser(42, true).subscribe();

        const request = httpMock.expectOne('/api/admin/users/42/?dry_run=true');
        expect(request.request.method).toBe('DELETE');
        expect(request.request.body).toBeNull();
        request.flush(REPORT);
    });

    it('sends the verification phrase in the body of the real delete', () => {
        service.deleteUser(42, false, 'delete-jane@example.com').subscribe();

        const request = httpMock.expectOne('/api/admin/users/42/?dry_run=false');
        expect(request.request.method).toBe('DELETE');
        expect(request.request.body).toEqual({ verification_phrase: 'delete-jane@example.com' });
        request.flush(REPORT);
    });
});
