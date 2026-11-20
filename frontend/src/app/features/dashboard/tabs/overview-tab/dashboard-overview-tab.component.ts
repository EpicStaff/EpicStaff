import { ChangeDetectionStrategy, Component, computed, inject } from '@angular/core';
import { FetchErrorStateComponent, LoadingSpinnerComponent } from '@shared/components';
import { GraphSessionStatus } from '@shared/models';
import { formatFileSize } from '@shared/utils';

import { ActiveTriggersCardComponent } from '../../components/active-triggers-card/active-triggers-card.component';
import { FirstReportStateComponent } from '../../components/first-report-state/first-report-state.component';
import { KpiCardComponent } from '../../components/kpi-card/kpi-card.component';
import { ResourceCardComponent } from '../../components/resource-card/resource-card.component';
import { DashboardResourceCard } from '../../models/dashboard-card.model';
import { DashboardTotals } from '../../models/dashboard-report.model';
import { DashboardReportService } from '../../services/dashboard-report.service';

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

    protected readonly resourceCards = computed(() => {
        const totals = this.report()?.totals;
        return totals ? toResourceCards(totals) : [];
    });
}

function toResourceCards(totals: DashboardTotals): DashboardResourceCard[] {
    return [
        { icon: 'ti-robot', label: 'Agents', value: totals.agents, details: [] },
        { icon: 'ti-share', label: 'Flows', value: totals.flows, details: [] },
        {
            icon: 'ti-briefcase',
            label: 'Roles',
            value: totals.roles_builtin + totals.roles_custom,
            details: [
                { value: totals.roles_builtin, label: 'built-in' },
                { value: totals.roles_custom, label: 'custom' },
            ],
        },
        { icon: 'ti-users', label: 'Users', value: totals.users, details: [] },
        {
            icon: 'ti-books',
            label: 'Knowledge',
            value: totals.knowledge_total,
            details: [
                { value: totals.knowledge_naive, label: 'Naive RAG' },
                { value: totals.knowledge_graph, label: 'GraphRAG' },
                { value: totals.knowledge_not_indexed, label: 'no RAG' },
            ],
        },
        {
            icon: 'ti-files',
            label: 'Files',
            value: totals.files,
            details: [{ value: formatFileSize(totals.files_bytes, 'auto'), label: 'in total' }],
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
        },
        {
            icon: 'ti-tools',
            label: 'Tools',
            value: totals.tools_python + totals.tools_mcp,
            details: [
                { value: totals.tools_python, label: 'custom' },
                { value: totals.tools_mcp, label: 'MCP' },
            ],
        },
        { icon: 'ti-puzzle', label: 'Plugins', value: totals.plugins, details: [] },
    ];
}
