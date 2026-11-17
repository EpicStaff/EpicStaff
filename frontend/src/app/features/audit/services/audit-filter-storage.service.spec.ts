import { provideHttpClient } from '@angular/common/http';
import { provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { AppStorageService } from '@shared/services';

import { provideAuditStorages } from '../audit.providers';
import { EMPTY_AUDIT_FILTER } from '../models/audit-filter.models';
import {
    auditFilterStorageKey,
    readStoredAuditFilter,
    writeStoredAuditFilter,
} from '../utils/audit-filter-storage.util';

describe('AuditFilterStorageService', () => {
    beforeEach(() => {
        localStorage.clear();
        // The audit token storage registered alongside needs HTTP; no request is made.
        TestBed.configureTestingModule({
            providers: [...provideAuditStorages(), provideHttpClient(), provideHttpClientTesting()],
        });
    });
    afterEach(() => localStorage.clear());

    it('forgets the saved audit filters of every organization when the session ends', () => {
        const ownFilter = { ...EMPTY_AUDIT_FILTER, mode: 'query' as const, query: 'user = "alice@example.com"' };
        writeStoredAuditFilter(auditFilterStorageKey(1, 'applied'), ownFilter);
        writeStoredAuditFilter(auditFilterStorageKey(1, 'draft'), ownFilter);
        writeStoredAuditFilter(auditFilterStorageKey(2, 'applied'), ownFilter);

        TestBed.inject(AppStorageService).clearAll();

        expect(readStoredAuditFilter(auditFilterStorageKey(1, 'applied'))).toEqual(EMPTY_AUDIT_FILTER);
        expect(readStoredAuditFilter(auditFilterStorageKey(1, 'draft'))).toEqual(EMPTY_AUDIT_FILTER);
        expect(readStoredAuditFilter(auditFilterStorageKey(2, 'applied'))).toEqual(EMPTY_AUDIT_FILTER);
    });
});
