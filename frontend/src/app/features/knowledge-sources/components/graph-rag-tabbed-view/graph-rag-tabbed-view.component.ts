import { ChangeDetectionStrategy, Component, computed, inject, input, signal } from '@angular/core';
import { MatTooltip } from '@angular/material/tooltip';
import { TabButtonComponent } from '@shared/components';

import { CollectionsStorageService } from '../../services/collections-storage.service';
import { GraphRagDataTablesComponent } from '../graph-rag-data-tables/graph-rag-data-tables.component';
import { GraphRagVisualizationComponent } from '../graph-rag-visualization/graph-rag-visualization.component';

export type GraphRagTab = 'configuration' | 'visualization' | 'data-tables';

@Component({
    selector: 'app-graph-rag-tabbed-view',
    templateUrl: './graph-rag-tabbed-view.component.html',
    styleUrls: ['./graph-rag-tabbed-view.component.scss'],
    imports: [TabButtonComponent, MatTooltip, GraphRagVisualizationComponent, GraphRagDataTablesComponent],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class GraphRagTabbedViewComponent {
    private collectionsStorage = inject(CollectionsStorageService);

    readonly ragId = input.required<number>();
    readonly activeTab = signal<GraphRagTab>('configuration');

    readonly showTabs = computed(() => {
        const usage = this.collectionsStorage.getRagIndexingUsage(this.ragId(), 'graph');
        return usage?.last_run != null || usage?.total != null;
    });

    onTabChange(tab: GraphRagTab): void {
        this.activeTab.set(tab);
    }
}
