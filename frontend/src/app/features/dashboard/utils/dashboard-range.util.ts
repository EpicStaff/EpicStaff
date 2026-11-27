import { DashboardFilters, DashboardPeriodUnit } from '../models/dashboard-filters.model';

export interface DashboardRange {
    from: Date;
    to: Date;
}

export function toRange({ period, unit }: DashboardFilters, to = todayUtc()): DashboardRange {
    const from = new Date(to);
    if (unit === DashboardPeriodUnit.Day) from.setUTCDate(from.getUTCDate() - (period - 1));
    if (unit === DashboardPeriodUnit.Month) from.setUTCMonth(from.getUTCMonth() - (period - 1), 1);
    if (unit === DashboardPeriodUnit.Year) from.setUTCFullYear(from.getUTCFullYear() - (period - 1), 0, 1);
    return { from, to };
}

export function toPreviousRange(filters: DashboardFilters, current: DashboardRange): DashboardRange {
    const to = new Date(current.from);
    to.setUTCDate(to.getUTCDate() - 1);
    return toRange(filters, to);
}

export function toIsoDate(date: Date): string {
    return date.toISOString().slice(0, 10);
}

function todayUtc(): Date {
    const now = new Date();
    return new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate()));
}
