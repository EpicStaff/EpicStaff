import { OrganizationRetention } from '@shared/models';

import { buildDashboardScheduleUpdate, toDashboardScheduleValue } from './dashboard-schedule.util';

function retention(overrides: Partial<OrganizationRetention> = {}): OrganizationRetention {
    return {
        org_id: 5,
        sessions_days: null,
        sessions_effective_days: 30,
        conversations_days: null,
        conversations_effective_days: 90,
        audit_days: null,
        audit_effective_days: 0,
        updated_at: null,
        updated_by: null,
        retention_policy: {
            sessions: { default_days: 30, max_days: null, min_days: null, allowed: [30] },
            conversations: { default_days: 90, max_days: null, min_days: null, allowed: [90] },
            audit: { default_days: 0, max_days: null, min_days: null, allowed: [0] },
        },
        dashboard_refresh_minutes: null,
        dashboard_refresh_daily_at: null,
        dashboard_refresh_policy: { default_minutes: 60, min_minutes: 15, max_minutes: 1440 },
        ...overrides,
    };
}

describe('toDashboardScheduleValue', () => {
    it('shows the default with the default interval and 06:00 ready for the other modes', () => {
        expect(toDashboardScheduleValue(retention())).toEqual({
            mode: 'default',
            dashboard_refresh_minutes: 60,
            dashboard_refresh_daily_at: '06:00',
        });
    });

    it('shows a stored interval', () => {
        expect(toDashboardScheduleValue(retention({ dashboard_refresh_minutes: 30 }))).toMatchObject({
            mode: 'minutes',
            dashboard_refresh_minutes: 30,
        });
    });

    it('shows a stored daily time', () => {
        expect(toDashboardScheduleValue(retention({ dashboard_refresh_daily_at: '21:30' }))).toMatchObject({
            mode: 'daily',
            dashboard_refresh_daily_at: '21:30',
        });
    });
});

describe('buildDashboardScheduleUpdate', () => {
    it('sends nothing when the schedule is unchanged', () => {
        const stored = retention({ dashboard_refresh_minutes: 30 });

        expect(buildDashboardScheduleUpdate(stored, toDashboardScheduleValue(stored))).toBeNull();
    });

    it('sends the interval and clears the daily time', () => {
        const stored = retention({ dashboard_refresh_daily_at: '06:00' });

        expect(
            buildDashboardScheduleUpdate(stored, {
                mode: 'minutes',
                dashboard_refresh_minutes: 45,
                dashboard_refresh_daily_at: '06:00',
            })
        ).toEqual({ dashboard_refresh_minutes: 45, dashboard_refresh_daily_at: null });
    });

    it('sends the minimum when the interval field was cleared, as the stepper does on blur', () => {
        expect(
            buildDashboardScheduleUpdate(retention(), {
                mode: 'minutes',
                dashboard_refresh_minutes: null,
                dashboard_refresh_daily_at: '06:00',
            })
        ).toEqual({ dashboard_refresh_minutes: 15, dashboard_refresh_daily_at: null });
    });

    it('sends the daily time and clears the interval', () => {
        const stored = retention({ dashboard_refresh_minutes: 30 });

        expect(
            buildDashboardScheduleUpdate(stored, {
                mode: 'daily',
                dashboard_refresh_minutes: 30,
                dashboard_refresh_daily_at: '07:30',
            })
        ).toEqual({ dashboard_refresh_minutes: null, dashboard_refresh_daily_at: '07:30' });
    });

    it('sends both nulls when switching back to the default', () => {
        const stored = retention({ dashboard_refresh_minutes: 30 });

        expect(
            buildDashboardScheduleUpdate(stored, {
                mode: 'default',
                dashboard_refresh_minutes: 30,
                dashboard_refresh_daily_at: '06:00',
            })
        ).toEqual({ dashboard_refresh_minutes: null, dashboard_refresh_daily_at: null });
    });
});
