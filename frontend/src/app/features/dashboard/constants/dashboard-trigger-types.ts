import { DashboardTriggerType } from '../models/dashboard-report.model';

export const DASHBOARD_TRIGGER_TYPES: Record<DashboardTriggerType, { icon: string; label: string; status: string }> = {
    [DashboardTriggerType.Schedule]: { icon: 'ti-calendar-event', label: 'Schedule', status: 'Active' },
    [DashboardTriggerType.Webhook]: { icon: 'ti-world', label: 'Webhook', status: 'Listening' },
    [DashboardTriggerType.Telegram]: { icon: 'ti-brand-telegram', label: 'Telegram', status: 'Listening' },
};
