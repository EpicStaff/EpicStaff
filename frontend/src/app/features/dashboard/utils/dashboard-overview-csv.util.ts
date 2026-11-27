import { GraphSessionStatus } from '@shared/models';

import { DASHBOARD_SESSION_STATUSES } from '../constants/dashboard-session-statuses';
import { DASHBOARD_TRIGGER_TYPES } from '../constants/dashboard-trigger-types';
import { DashboardResourceCard } from '../models/dashboard-card.model';
import { DashboardCsvSection } from '../models/dashboard-export.model';
import { DashboardReport } from '../models/dashboard-report.model';
import { DashboardStats } from '../models/dashboard-stats.model';
import { DashboardRange, toIsoDate } from './dashboard-range.util';
import { sumStats } from './dashboard-stats.util';

export interface DashboardOverviewCsvData {
    report: DashboardReport;
    stats: DashboardStats | null;
    range: DashboardRange;
    resourceCards: DashboardResourceCard[];
}

export function toOverviewCsv({
    report,
    stats,
    range,
    resourceCards,
}: DashboardOverviewCsvData): DashboardCsvSection[] {
    const waiting = report.live_sessions.filter((session) => session.status === GraphSessionStatus.WAITING_FOR_USER);
    const totals = stats ? sumStats(stats) : null;

    const summary: DashboardCsvSection = {
        title: 'Summary',
        header: ['Metric', 'Value'],
        rows: [
            ['From', toIsoDate(range.from)],
            ['To', toIsoDate(range.to)],
            ['Sessions', totals?.sessions],
            ['Failed sessions', totals?.errors],
            ['Error rate %', totals && (totals.sessions ? ((totals.errors / totals.sessions) * 100).toFixed(1) : 0)],
            ['Tokens', totals?.tokens],
            ['Active triggers', report.active_triggers.length],
            ['Sessions waiting for user', waiting.length],
            ['Report built at', toUtcDateTime(report.built_at)],
        ],
    };

    const sessionsByStatus: DashboardCsvSection = {
        title: 'Sessions by status',
        header: ['Period', ...DASHBOARD_SESSION_STATUSES.map((status) => status.label), 'Total'],
        rows: (stats?.periods ?? []).map(({ period, by_status }) => {
            const counts = DASHBOARD_SESSION_STATUSES.map((status) => by_status[status.key]);
            return [period, ...counts, counts.reduce((sum, count) => sum + count, 0)];
        }),
    };

    const activeTriggers: DashboardCsvSection = {
        title: 'Active triggers',
        header: ['Type', 'Flow', 'Node or session', 'Status', 'Next run', 'Last event'],
        rows: [
            ...waiting.map((session) => [
                'Waiting session',
                session.graph_name,
                `Session #${session.session_id}`,
                'Waiting for user',
                null,
                toUtcDateTime(session.created_at),
            ]),
            ...report.active_triggers.map((trigger) => {
                const type = DASHBOARD_TRIGGER_TYPES[trigger.trigger_type];
                return [
                    type.label,
                    trigger.graph_name,
                    trigger.node_name,
                    type.status,
                    toUtcDateTime(trigger.next_run_at),
                    toUtcDateTime(trigger.last_event_at),
                ];
            }),
        ],
    };

    const resources: DashboardCsvSection = {
        title: 'Resources',
        header: ['Resource', 'Total', 'Details'],
        rows: resourceCards.map((card) => [
            card.label,
            card.value,
            card.details.map((detail) => `${detail.value} ${detail.label}`).join('; '),
        ]),
    };

    return [summary, sessionsByStatus, activeTriggers, resources];
}

function toUtcDateTime(value: string | null): string | null {
    return value && `${new Date(value).toISOString().slice(0, 16).replace('T', ' ')} UTC`;
}
