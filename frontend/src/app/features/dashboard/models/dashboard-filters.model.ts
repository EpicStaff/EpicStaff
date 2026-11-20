export enum DashboardPeriodUnit {
    Day = 'day',
    Month = 'month',
    Year = 'year',
}

export interface DashboardFilters {
    period: number;
    unit: DashboardPeriodUnit;
}

export const DEFAULT_DASHBOARD_FILTERS: DashboardFilters = {
    period: 14,
    unit: DashboardPeriodUnit.Day,
};
