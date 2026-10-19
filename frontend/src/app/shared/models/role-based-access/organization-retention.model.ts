import { UserSummary } from '../authorship.model';

export type RetentionDataType = 'sessions' | 'conversations' | 'audit';

/** The instance bounds for one data type. Days of 0 mean "keep forever". */
export interface RetentionRule {
    default_days: number;
    /** Null when the instance sets no cap. */
    max_days: number | null;
    /** The values an organization may choose, in display order. */
    allowed: number[];
}

export type RetentionPolicy = Record<RetentionDataType, RetentionRule>;

/**
 * GET / PATCH /api/admin/organizations/{id}/retention/.
 * `*_days` is the organization's choice: null means the instance default, 0 means unlimited.
 * `*_effective_days` is what is actually applied after the default and the cap.
 */
export interface OrganizationRetention {
    org_id: number;
    sessions_days: number | null;
    sessions_effective_days: number;
    conversations_days: number | null;
    conversations_effective_days: number;
    audit_days: number | null;
    audit_effective_days: number;
    /** Null while the organization has never changed its retention. */
    updated_at: string | null;
    updated_by: UserSummary | null;
    retention_policy: RetentionPolicy;
}

/** A non-empty subset of the choices; unsent types are left unchanged. */
export type OrganizationRetentionUpdate = Partial<
    Pick<OrganizationRetention, 'sessions_days' | 'conversations_days' | 'audit_days'>
>;
