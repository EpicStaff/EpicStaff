import { HttpErrorResponse } from '@angular/common/http';
import { ChangeDetectionStrategy, Component, computed, inject, OnInit, signal, viewChild } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { ButtonComponent } from '@shared/components';
import { EMPTY, Observable, of } from 'rxjs';
import { filter, switchMap, tap } from 'rxjs/operators';

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
    hasUnsavedChanges = computed(() => this.ragConfiguration()?.hasUnsavedChanges() ?? false);
    indexingDisabled = computed(() => !this.docConfigIds().length && !this.hasUnsavedChanges());
    runButtonLabel = computed(() => {
        return this.ragConfiguration()?.indexMode() === 'total_reindex' ? 'Save & Re-index' : 'Save & Run Index';
    });
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
        if (!this.hasUnsavedChanges()) {
            this.dialogRef.close();
            return;
        }

        this.confirmation
            .confirm({
                title: 'Unsaved Changes',
                message: 'You have unsaved changes in your Graph RAG Configuration. Would you like to leave?',
                type: 'warning',
                cancelText: 'Cancel',
                confirmText: 'Leave',
            })
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe((result) => {
                if (result === true) this.dialogRef.close();
            });
    }

    runIndexing() {
        const ragComponent = this.ragConfiguration();
        if (!ragComponent) return;

        const config = ragComponent.getConfigurationData();
        if (!config) return;

        const ragId = this.data.ragId;
        const configIds = this.docConfigIds();
        const shouldSave = ragComponent.shouldSaveConfig();
        const pendingDeleteIds = ragComponent.getPendingDeleteDocumentIds();

        if (!configIds.length && !this.hasUnsavedChanges()) return;

        const delete$: Observable<unknown> = pendingDeleteIds.length ? ragComponent.bulkDeletePending(ragId) : of(null);

        const save$: Observable<unknown> = shouldSave
            ? this.graphRagService
                  .updateRagIndexConfigs(ragId, config)
                  .pipe(
                      tap(() =>
                          this.graphRag.update((prev) =>
                              prev ? { ...prev, index_config: { ...prev.index_config, ...config } } : prev
                          )
                      )
                  )
            : of(null);

        this.confirmation
            .confirm(getIndexingConfirmationData(ragComponent.getIndexingDocuments()))
            .pipe(
                filter((result) => result === true),
                switchMap(() => delete$),
                switchMap(() => save$),
                switchMap(() => {
                    if (!configIds.length) {
                        this.toast.success('Changes saved');
                        return EMPTY;
                    }
                    return this.ragIndexingService
                        .startIndexing({
                            rag_id: ragId,
                            rag_type: 'graph',
                            document_config_ids: configIds,
                        })
                        .pipe(
                            tap(() => {
                                this.toast.success('Indexing started');
                                this.collectionsStorage.markRagAsProcessing(ragId);
                                this.collectionsStorage.markConfigsAsProcessing(configIds);
                            })
                        );
                }),
                takeUntilDestroyed(this.destroyRef)
            )
            .subscribe({
                error: (err: HttpErrorResponse) => {
                    if (err?.validationErrors?.length) {
                        ragComponent.setServerValidationErrors(err.validationErrors);
                        return;
                    }
                    this.toast.error(err.error?.message || 'Files re-indexing failed');
                },
            });
    }
}
