import { ChangeDetectionStrategy, Component, computed, inject, OnInit, signal, viewChild } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { ButtonComponent } from '@shared/components';
import { filter, switchMap } from 'rxjs/operators';

import { getIndexingConfirmationData } from '../../../helpers/get-indexing-confirmation-data.util';
import { CollectionGraphRag } from '../../../models/graph-rag.model';
import { CollectionsStorageService } from '../../../services/collections-storage.service';
import { GraphRagService } from '../../../services/graph-rag.service';
import { GraphRagConfigurationComponent } from '../../graph-rag-configuration/graph-rag-configuration.component';
import { RagConfigurationDialogComponent } from '../rag-configuration-dialog.component';

@Component({
    selector: 'app-graph-rag-configuration-dialog',
    templateUrl: './graph-rag-configuration-dialog.component.html',
    styleUrls: ['../rag-configuration-dialog.component.scss'],
    imports: [ButtonComponent, GraphRagConfigurationComponent],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class GraphRagConfigurationDialog extends RagConfigurationDialogComponent implements OnInit {
    private graphRagService = inject(GraphRagService);
    private collectionsStorage = inject(CollectionsStorageService);
    private ragConfiguration = viewChild(GraphRagConfigurationComponent);

    graphRag = signal<CollectionGraphRag | null>(null);

    docConfigIds = computed(() => this.ragConfiguration()?.getDocumentConfigIds() ?? []);
    indexingDisabled = computed(() => !this.docConfigIds().length);

    isIndexing = computed(() => {
        for (const c of this.collectionsStorage.fullCollections()) {
            const config = c.rag_configurations.find((r) => r.rag_id === this.data.ragId);
            if (config) return config.status === 'processing';
        }
        return false;
    });

    ngOnInit() {
        this.getGraphRag(this.data.ragId);
    }

    getGraphRag(id: number): void {
        this.graphRagService
            .getRagById(id)
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe((graphRag) => this.graphRag.set(graphRag));
    }

    onClose() {
        this.dialogRef.close();
    }

    runIndexing() {
        this.confirmation
            .confirm(getIndexingConfirmationData([]))
            .pipe(
                filter((result) => result === true),
                switchMap(() =>
                    this.ragIndexingService.startIndexing({
                        rag_id: this.data.ragId,
                        rag_type: 'graph',
                        document_config_ids: this.docConfigIds(),
                    })
                ),
                takeUntilDestroyed(this.destroyRef)
            )
            .subscribe({
                next: () => {
                    this.toast.success('Indexing started');
                    this.collectionsStorage.markRagAsProcessing(this.data.ragId);
                },
                error: () => this.toast.error('Files re-indexing failed'),
            });
    }
}
