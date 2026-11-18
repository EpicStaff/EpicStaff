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

    it('forgets the saved audit filters of every organization and user when the session ends', () => {
        const ownFilter = { ...EMPTY_AUDIT_FILTER, mode: 'query' as const, query: 'user = "alice@example.com"' };
        const keys = [
            auditFilterStorageKey(1, 7, 'applied'),
            auditFilterStorageKey(1, 7, 'draft'),
            auditFilterStorageKey(1, 8, 'applied'),
            auditFilterStorageKey(2, 7, 'applied'),
        ];
        keys.forEach((key) => writeStoredAuditFilter(key, ownFilter));

        TestBed.inject(AppStorageService).clearAll();

        expect(keys.map((key) => readStoredAuditFilter(key))).toEqual(keys.map(() => EMPTY_AUDIT_FILTER));
    });
});
