import { AuditFilterState, EMPTY_AUDIT_FILTER } from '../models/audit-filter.models';
import {
    auditFilterStorageKey,
    clearStoredAuditFilters,
    readStoredAuditFilter,
    writeStoredAuditFilter,
} from './audit-filter-storage.util';

const ORG_ID = 1;
const USER_ID = 7;

describe('audit filter storage', () => {
    afterEach(() => {
        localStorage.clear();
        vi.restoreAllMocks();
    });

    it('round-trips the applied filter per organization', () => {
        const state: AuditFilterState = { ...EMPTY_AUDIT_FILTER, mode: 'query', query: 'status in ["failed"]' };
        writeStoredAuditFilter(auditFilterStorageKey(ORG_ID, USER_ID, 'applied'), state);

        expect(readStoredAuditFilter(auditFilterStorageKey(ORG_ID, USER_ID, 'applied'))).toEqual(state);
        expect(readStoredAuditFilter(auditFilterStorageKey(2, USER_ID, 'applied'))).toEqual(EMPTY_AUDIT_FILTER);
    });

    it("does not read another user's filter in the same organization", () => {
        const state: AuditFilterState = { ...EMPTY_AUDIT_FILTER, searchText: 'alice@example.com' };
        writeStoredAuditFilter(auditFilterStorageKey(ORG_ID, USER_ID, 'applied'), state);
        writeStoredAuditFilter(auditFilterStorageKey(ORG_ID, USER_ID, 'draft'), state);

        expect(readStoredAuditFilter(auditFilterStorageKey(ORG_ID, 8, 'applied'))).toEqual(EMPTY_AUDIT_FILTER);
        expect(readStoredAuditFilter(auditFilterStorageKey(ORG_ID, 8, 'draft'))).toEqual(EMPTY_AUDIT_FILTER);
    });

    it.each([
        ['organization', null, USER_ID],
        ['user', ORG_ID, null],
    ])('stores nothing without an %s', (_missing, organizationId, userId) => {
        writeStoredAuditFilter(auditFilterStorageKey(organizationId, userId, 'applied'), {
            ...EMPTY_AUDIT_FILTER,
            kinds: ['session'],
        });

        expect(localStorage.length).toBe(0);
    });

    it('keeps the draft apart from the applied filter and falls back to the given state', () => {
        const applied: AuditFilterState = { ...EMPTY_AUDIT_FILTER, kinds: ['session'] };
        const draft: AuditFilterState = { ...EMPTY_AUDIT_FILTER, kinds: ['event'] };
        const appliedKey = auditFilterStorageKey(ORG_ID, USER_ID, 'applied');
        const draftKey = auditFilterStorageKey(ORG_ID, USER_ID, 'draft');

        expect(readStoredAuditFilter(draftKey, applied)).toEqual(applied);

        writeStoredAuditFilter(appliedKey, applied);
        writeStoredAuditFilter(draftKey, draft);

        expect(readStoredAuditFilter(appliedKey)).toEqual(applied);
        expect(readStoredAuditFilter(draftKey, applied)).toEqual(draft);
    });

    it('falls back to the empty filter for a corrupt value', () => {
        localStorage.setItem(auditFilterStorageKey(ORG_ID, USER_ID, 'applied')!, '{not json');

        expect(readStoredAuditFilter(auditFilterStorageKey(ORG_ID, USER_ID, 'applied'))).toEqual(EMPTY_AUDIT_FILTER);
    });

    it('survives storage that throws', () => {
        vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
            throw new Error('blocked');
        });
        vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
            throw new Error('blocked');
        });
        const key = auditFilterStorageKey(ORG_ID, USER_ID, 'applied');

        expect(() => writeStoredAuditFilter(key, EMPTY_AUDIT_FILTER)).not.toThrow();
        expect(readStoredAuditFilter(key)).toEqual(EMPTY_AUDIT_FILTER);
    });

    it('clears audit filters in every stored format and leaves other keys alone', () => {
        const key = auditFilterStorageKey(ORG_ID, USER_ID, 'applied');
        writeStoredAuditFilter(key, { ...EMPTY_AUDIT_FILTER, kinds: ['session'] });
        // stored before the key named its user, and in an older format
        localStorage.setItem('epicstaff.audit.filter.v1.applied.1', '{}');
        localStorage.setItem('epicstaff.audit.filter.v0.applied.1', '{}');
        localStorage.setItem('epicstaff.theme', 'dark');

        clearStoredAuditFilters();

        expect(readStoredAuditFilter(key)).toEqual(EMPTY_AUDIT_FILTER);
        expect(localStorage.getItem('epicstaff.audit.filter.v1.applied.1')).toBeNull();
        expect(localStorage.getItem('epicstaff.audit.filter.v0.applied.1')).toBeNull();
        expect(localStorage.getItem('epicstaff.theme')).toBe('dark');
    });

    it('clears nothing, without throwing, when storage is blocked', () => {
        writeStoredAuditFilter(auditFilterStorageKey(ORG_ID, USER_ID, 'applied'), EMPTY_AUDIT_FILTER);
        vi.spyOn(Storage.prototype, 'key').mockImplementation(() => {
            throw new Error('blocked');
        });

        expect(() => clearStoredAuditFilters()).not.toThrow();
    });
});
