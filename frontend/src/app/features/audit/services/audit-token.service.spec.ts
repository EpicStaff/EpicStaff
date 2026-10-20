import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';

import { AuthService } from '../../../services/auth/auth.service';
import { ConfigService } from '../../../services/config';
import { AuditTokenService } from './audit-token.service';

describe('AuditTokenService', () => {
    let service: AuditTokenService;
    let httpMock: HttpTestingController;

    beforeEach(() => {
        TestBed.configureTestingModule({
            providers: [
                provideHttpClient(),
                provideHttpClientTesting(),
                { provide: ConfigService, useValue: { apiUrl: '/api/' } as unknown as ConfigService },
                { provide: AuthService, useValue: { getAccessToken: () => 'access' } as unknown as AuthService },
            ],
        });
        service = TestBed.inject(AuditTokenService);
        httpMock = TestBed.inject(HttpTestingController);
    });

    afterEach(() => httpMock.verify());

    function mint(token: string): string | undefined {
        let received: string | undefined;
        service.getToken().subscribe((value) => (received = value));
        httpMock.expectOne('/api/audit/token/').flush({ token, expires_in: 300 });
        return received;
    }

    it('reuses the cached token until cleared, then mints a new one', () => {
        expect(mint('first-user')).toBe('first-user');

        let cached: string | undefined;
        service.getToken().subscribe((value) => (cached = value));
        httpMock.expectNone('/api/audit/token/');
        expect(cached).toBe('first-user');

        // logout and org switch clear every APP_STORAGE entry; the next user must not get the old token
        service.clear();
        expect(mint('second-user')).toBe('second-user');
    });
});
