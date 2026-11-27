import { ChangeDetectionStrategy, Component, computed, DestroyRef, inject } from '@angular/core';
import { RouterLink } from '@angular/router';
import { FetchErrorStateComponent, LoadingSpinnerComponent } from '@shared/components';
import { GraphSessionStatus } from '@shared/models';
import { formatFileSize, formatTokens } from '@shared/utils';

import { ActiveTriggersCardComponent } from '../../components/active-triggers-card/active-triggers-card.component';
import { FirstReportStateComponent } from '../../components/first-report-state/first-report-state.component';
import { KpiCardComponent } from '../../components/kpi-card/kpi-card.component';
import { KpiDeltaComponent } from '../../components/kpi-delta/kpi-delta.component';
import { ResourceCardComponent } from '../../components/resource-card/resource-card.component';
import { SessionsByStatusCardComponent } from '../../components/sessions-by-status-card/sessions-by-status-card.component';
import { DashboardTab } from '../../constants/dashboard-tabs';
import { DashboardResourceCard } from '../../models/dashboard-card.model';
import { DashboardTotals } from '../../models/dashboard-report.model';
import { DashboardExportService } from '../../services/dashboard-export.service';
import { DashboardFiltersService } from '../../services/dashboard-filters.service';
import { DashboardReportService } from '../../services/dashboard-report.service';
import { DashboardStatsService } from '../../services/dashboard-stats.service';
import { toOverviewCsv } from '../../utils/dashboard-overview-csv.util';
import { toRange } from '../../utils/dashboard-range.util';
import { sumStats } from '../../utils/dashboard-stats.util';

@Component({
    selector: 'app-dashboard-overview-tab',
    templateUrl: './dashboard-overview-tab.component.html',
    styleUrls: ['./dashboard-overview-tab.component.scss'],
    imports: [
        KpiCardComponent,
        ActiveTriggersCardComponent,
        ResourceCardComponent,
        FirstReportStateComponent,
        FetchErrorStateComponent,
        LoadingSpinnerComponent,
        KpiDeltaComponent,
        SessionsByStatusCardComponent,
        RouterLink,
    ],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class DashboardOverviewTabComponent {
    private readonly reportService = inject(DashboardReportService);

    protected readonly resource = this.reportService.resource;
    protected readonly report = this.reportService.report;

    protected readonly waitingSessions = computed(() =>
        (this.report()?.live_sessions ?? []).filter((session) => session.status === GraphSessionStatus.WAITING_FOR_USER)
    );

    protected readonly liveNow = computed(
        () =>
            (this.report()?.live_sessions ?? []).filter(
                (session) =>
                    session.status === GraphSessionStatus.RUNNING || session.status === GraphSessionStatus.PENDING
            ).length
    );

    protected readonly resourceCards = computed(() => {
        const totals = this.report()?.totals;
        return totals ? toResourceCards(totals) : [];
    });

    protected readonly stats = inject(DashboardStatsService).resource;
    protected readonly filters = inject(DashboardFiltersService).filters;

    protected readonly kpis = computed(() => {
        if (!this.stats.hasValue()) return null;
        const current = sumStats(this.stats.value().current);
        const previous = sumStats(this.stats.value().previous);
        return {
            current,
            previous,
            sessions: current.sessions.toLocaleString('en-US'),
            tokens: formatTokens(current.tokens),
            errorRate: current.sessions ? ((current.errors / current.sessions) * 100).toFixed(1) : '0',
        };
    });

    protected readonly previousLabel = computed(() => {
        const { period, unit } = this.filters();
        return `vs previous ${period} ${unit}${period === 1 ? '' : 's'}`;
    });

    private readonly csvSections = computed(() => {
        const report = this.report();
        if (!report) return [];
        return toOverviewCsv({
            report,
            stats: this.stats.hasValue() ? this.stats.value().current : null,
            range: toRange(this.filters()),
            resourceCards: this.resourceCards(),
        });
    });

    constructor() {
        inject(DashboardExportService).register(
            { name: DashboardTab.Overview, sections: this.csvSections },
            inject(DestroyRef)
        );
    }
}

function toResourceCards(totals: DashboardTotals): DashboardResourceCard[] {
    return [
        { icon: 'ti-robot', label: 'Agents', value: totals.agents, details: [], link: '/agents' },
        { icon: 'ti-share', label: 'Flows', value: totals.flows, details: [], link: '/flows' },
        {
            icon: 'ti-briefcase',
            label: 'Roles',
            value: totals.roles_builtin + totals.roles_custom,
            details: [
                { value: totals.roles_builtin, label: 'built-in' },
                { value: totals.roles_custom, label: 'custom' },
            ],
            link: '/workspace/roles',
        },
        { icon: 'ti-users', label: 'Users', value: totals.users, details: [], link: '/workspace/users' },
        {
            icon: 'ti-books',
            label: 'Knowledge',
            value: totals.knowledge_total,
            details: [
                { value: totals.knowledge_naive, label: 'Naive RAG' },
                { value: totals.knowledge_graph, label: 'GraphRAG' },
                { value: totals.knowledge_not_indexed, label: 'no RAG' },
            ],
            link: '/storage/knowledge-sources',
        },
        {
            icon: 'ti-files',
            label: 'Files',
            value: totals.files,
            details: [{ value: formatFileSize(totals.files_bytes, 'auto'), label: 'in total' }],
            link: '/storage/files',
        },
        {
            icon: 'ti-cpu',
            label: 'AI model configs',
            value: totals.llm_configs + totals.embedding_configs + totals.realtime_configs,
            details: [
                { value: totals.llm_configs, label: 'LLM' },
                { value: totals.embedding_configs, label: 'embedding' },
                { value: totals.realtime_configs, label: 'realtime' },
            ],
            link: '/settings/llm-library',
        },
        {
            icon: 'ti-tools',
            label: 'Tools',
            value: totals.tools_python + totals.tools_mcp,
            details: [
                { value: totals.tools_python, label: 'custom' },
                { value: totals.tools_mcp, label: 'MCP' },
            ],
            link: '/tools',
        },
        { icon: 'ti-puzzle', label: 'Plugins', value: totals.plugins, details: [], link: '/workspace/plugins' },
    ];
}
