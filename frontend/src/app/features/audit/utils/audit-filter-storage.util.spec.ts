import { AuditFilterState, EMPTY_AUDIT_FILTER } from '../models/audit-filter.models';
import {
    auditFilterStorageKey,
    clearStoredAuditFilters,
    readStoredAuditFilter,
    writeStoredAuditFilter,
} from './audit-filter-storage.util';

describe('audit filter storage', () => {
    afterEach(() => {
        localStorage.clear();
        vi.restoreAllMocks();
    });

    it('round-trips the applied filter per organization', () => {
        const state: AuditFilterState = { ...EMPTY_AUDIT_FILTER, mode: 'query', query: 'status in ["failed"]' };
        writeStoredAuditFilter(auditFilterStorageKey(1, 'applied'), state);

        expect(readStoredAuditFilter(auditFilterStorageKey(1, 'applied'))).toEqual(state);
        expect(readStoredAuditFilter(auditFilterStorageKey(2, 'applied'))).toEqual(EMPTY_AUDIT_FILTER);
    });

    it('keeps the draft apart from the applied filter and falls back to the given state', () => {
        const applied: AuditFilterState = { ...EMPTY_AUDIT_FILTER, kinds: ['session'] };
        const draft: AuditFilterState = { ...EMPTY_AUDIT_FILTER, kinds: ['event'] };

        expect(readStoredAuditFilter(auditFilterStorageKey(1, 'draft'), applied)).toEqual(applied);

        writeStoredAuditFilter(auditFilterStorageKey(1, 'applied'), applied);
        writeStoredAuditFilter(auditFilterStorageKey(1, 'draft'), draft);

        expect(readStoredAuditFilter(auditFilterStorageKey(1, 'applied'))).toEqual(applied);
        expect(readStoredAuditFilter(auditFilterStorageKey(1, 'draft'), applied)).toEqual(draft);
    });

    it('falls back to the empty filter for a corrupt value', () => {
        localStorage.setItem(auditFilterStorageKey(1, 'applied')!, '{not json');

        expect(readStoredAuditFilter(auditFilterStorageKey(1, 'applied'))).toEqual(EMPTY_AUDIT_FILTER);
    });

    it('survives storage that throws', () => {
        vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
            throw new Error('blocked');
        });
        vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
            throw new Error('blocked');
        });

        expect(() => writeStoredAuditFilter(auditFilterStorageKey(1, 'applied'), EMPTY_AUDIT_FILTER)).not.toThrow();
        expect(readStoredAuditFilter(auditFilterStorageKey(1, 'applied'))).toEqual(EMPTY_AUDIT_FILTER);
    });

    it('clears audit filters in every stored format and leaves other keys alone', () => {
        writeStoredAuditFilter(auditFilterStorageKey(1, 'applied'), { ...EMPTY_AUDIT_FILTER, kinds: ['session'] });
        localStorage.setItem('epicstaff.audit.filter.v0.applied.1', '{}');
        localStorage.setItem('epicstaff.theme', 'dark');

        clearStoredAuditFilters();

        expect(readStoredAuditFilter(auditFilterStorageKey(1, 'applied'))).toEqual(EMPTY_AUDIT_FILTER);
        expect(localStorage.getItem('epicstaff.audit.filter.v0.applied.1')).toBeNull();
        expect(localStorage.getItem('epicstaff.theme')).toBe('dark');
    });

    it('clears nothing, without throwing, when storage is blocked', () => {
        writeStoredAuditFilter(auditFilterStorageKey(1, 'applied'), EMPTY_AUDIT_FILTER);
        vi.spyOn(Storage.prototype, 'key').mockImplementation(() => {
            throw new Error('blocked');
        });

        expect(() => clearStoredAuditFilters()).not.toThrow();
    });
});
