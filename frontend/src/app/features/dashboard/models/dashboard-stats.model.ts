export interface DashboardStatusCounts {
    end: number;
    error: number;
    stop: number;
    expired: number;
}

export interface DashboardTokenTotals {
    prompt: number;
    completion: number;
    cached: number;
    total: number;
    cost_usd: string;
}

export interface DashboardStatsPeriod {
    period: string;
    by_status: DashboardStatusCounts;
    tokens: DashboardTokenTotals;
}

export interface DashboardStats {
    periods: DashboardStatsPeriod[];
}
