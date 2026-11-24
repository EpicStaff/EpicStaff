import { DashboardStatusCounts } from '../models/dashboard-stats.model';

export const DASHBOARD_SESSION_STATUSES: { key: keyof DashboardStatusCounts; label: string; color: string }[] = [
    { key: 'end', label: 'Completed', color: '--color-session-end' },
    { key: 'error', label: 'Error', color: '--color-session-error' },
    { key: 'stop', label: 'Stopped', color: '--color-session-stop' },
    { key: 'expired', label: 'Expired', color: '--color-session-expired' },
];
