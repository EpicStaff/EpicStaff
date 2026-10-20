import { ActionCode, ResourceCode, RolePermission } from '@shared/models';

export type AuditHistoryUnit = 'unlimited' | 'years' | 'months' | 'days';

export const AUDIT_HISTORY_DAYS_PER_UNIT: Record<AuditHistoryUnit, number> = {
    unlimited: 0,
    years: 365,
    months: 30,
    days: 1,
};
// the backend's upper bound for audit_history_days; 0 means unlimited
export const MAX_AUDIT_HISTORY_DAYS = 36_500;
// unlimited, matching the backend default for a role created without the field
export const DEFAULT_AUDIT_HISTORY_DAYS = 0;

export interface AuditHistoryRange {
    unit: AuditHistoryUnit;
    amount: number;
}

const UNIT_NAMES: Record<Exclude<AuditHistoryUnit, 'unlimited'>, string> = {
    years: 'year',
    months: 'month',
    days: 'day',
};

// The backend stores days only; show them in the largest unit that divides evenly: 730 → 2 years, 90 → 3 months, 45 → 45 days.
export function splitAuditHistoryDays(days: number): AuditHistoryRange {
    if (days === 0) {
        return { unit: 'unlimited', amount: 1 };
    }
    if (days % AUDIT_HISTORY_DAYS_PER_UNIT.years === 0) {
        return { unit: 'years', amount: days / AUDIT_HISTORY_DAYS_PER_UNIT.years };
    }
    if (days % AUDIT_HISTORY_DAYS_PER_UNIT.months === 0) {
        return { unit: 'months', amount: days / AUDIT_HISTORY_DAYS_PER_UNIT.months };
    }
    return { unit: 'days', amount: days };
}

// Unlimited is 0 days per unit, so it always comes out as 0
export function auditHistoryRangeToDays(range: AuditHistoryRange): number {
    return range.amount * AUDIT_HISTORY_DAYS_PER_UNIT[range.unit];
}

// The limit lives on the audit permission entry; a missing entry or value means unlimited
export function auditHistoryDaysOf(permissions: RolePermission[]): number {
    return permissions.find((permission) => permission.resource_type === ResourceCode.Audit)?.audit_history_days ?? 0;
}

// permissions is a full replacement on write, so the limit must ride along on the audit entry or the role becomes unlimited.
// The backend rejects a non-zero limit on an audit entry without read or export, so it is attached only when one is granted.
export function withAuditHistoryDays(permissions: RolePermission[], days: number): RolePermission[] {
    return permissions.map((permission) =>
        days !== 0 &&
        permission.resource_type === ResourceCode.Audit &&
        (permission.actions.includes(ActionCode.Read) || permission.actions.includes(ActionCode.Export))
            ? { ...permission, audit_history_days: days }
            : permission
    );
}

export function formatAuditHistoryDays(days: number): string {
    const { unit, amount } = splitAuditHistoryDays(days);
    if (unit === 'unlimited') {
        return 'Unlimited';
    }
    return `${amount} ${UNIT_NAMES[unit]}${amount === 1 ? '' : 's'}`;
}
