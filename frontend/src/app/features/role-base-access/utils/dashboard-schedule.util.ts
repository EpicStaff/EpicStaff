import { OrganizationRetention, OrganizationRetentionUpdate } from '@shared/models';

export type DashboardScheduleMode = 'default' | 'minutes' | 'daily';

export interface DashboardScheduleValue {
    mode: DashboardScheduleMode;
    dashboard_refresh_minutes: number | null;
    dashboard_refresh_daily_at: string;
}

export const DEFAULT_DASHBOARD_DAILY_AT = '06:00';

export function toDashboardScheduleValue(retention: OrganizationRetention): DashboardScheduleValue {
    const minutes = retention.dashboard_refresh_minutes;
    const dailyAt = retention.dashboard_refresh_daily_at;
    return {
        mode: dailyAt ? 'daily' : minutes ? 'minutes' : 'default',
        dashboard_refresh_minutes: minutes ?? retention.dashboard_refresh_policy.default_minutes,
        dashboard_refresh_daily_at: dailyAt ?? DEFAULT_DASHBOARD_DAILY_AT,
    };
}

export function buildDashboardScheduleUpdate(
    retention: OrganizationRetention,
    value: DashboardScheduleValue
): OrganizationRetentionUpdate | null {
    const minutes =
        value.mode === 'minutes'
            ? (value.dashboard_refresh_minutes ?? retention.dashboard_refresh_policy.min_minutes)
            : null;
    const dailyAt = value.mode === 'daily' ? value.dashboard_refresh_daily_at : null;
    if (minutes === retention.dashboard_refresh_minutes && dailyAt === retention.dashboard_refresh_daily_at) {
        return null;
    }
    return { dashboard_refresh_minutes: minutes, dashboard_refresh_daily_at: dailyAt };
}
