import { ChangeDetectionStrategy, Component, computed, inject, input, signal } from '@angular/core';
import { MatTooltip } from '@angular/material/tooltip';
import { TabButtonComponent } from '@shared/components';

import { CollectionsStorageService } from '../../services/collections-storage.service';
import {
    GraphRagDataTablesComponent,
    GraphRagPendingOpenIn,
} from '../graph-rag-data-tables/graph-rag-data-tables.component';
import {
    GraphRagOpenInRequest,
    GraphRagVisualizationComponent,
} from '../graph-rag-visualization/graph-rag-visualization.component';

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
    /**
     * Payload handed to the data-tables tab by an Open-in pick in the visualization. The data-tables
     * component consumes it once after its summary resolves; later tab toggles do not re-apply it.
     */
    readonly pendingOpenIn = signal<GraphRagPendingOpenIn | null>(null);

    readonly showTabs = computed(() => {
        const usage = this.collectionsStorage.getRagIndexingUsage(this.ragId(), 'graph');
        return usage?.last_run != null || usage?.total != null;
    });

    onTabChange(tab: GraphRagTab): void {
        this.activeTab.set(tab);
    }

    onOpenInRequested(request: GraphRagOpenInRequest): void {
        this.pendingOpenIn.set({
            subject: request.subject,
            linkedToType: request.linkedToType,
            linkedToId: request.linkedToId,
        });
        this.activeTab.set('data-tables');
    }
}
