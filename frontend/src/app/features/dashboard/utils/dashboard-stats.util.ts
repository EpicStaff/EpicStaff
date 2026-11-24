import { DashboardStats } from '../models/dashboard-stats.model';

export interface DashboardStatsTotals {
    sessions: number;
    errors: number;
    tokens: number;
}

export function sumStats({ periods }: DashboardStats): DashboardStatsTotals {
    return periods.reduce(
        (totals, { by_status, tokens }) => ({
            sessions: totals.sessions + by_status.end + by_status.error + by_status.stop + by_status.expired,
            errors: totals.errors + by_status.error,
            tokens: totals.tokens + tokens.total,
        }),
        { sessions: 0, errors: 0, tokens: 0 }
    );
}
