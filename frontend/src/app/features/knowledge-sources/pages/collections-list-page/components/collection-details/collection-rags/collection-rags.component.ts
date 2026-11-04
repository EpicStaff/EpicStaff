import { Dialog } from '@angular/cdk/dialog';
import { ComponentType } from '@angular/cdk/overlay';
import { DOCUMENT } from '@angular/common';
import {
    afterNextRender,
    ChangeDetectionStrategy,
    Component,
    computed,
    DestroyRef,
    ElementRef,
    inject,
    Injector,
    input,
    output,
    signal,
    viewChildren,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { MatTooltip } from '@angular/material/tooltip';
import { AppSvgIconComponent, ConfirmationDialogService } from '@shared/components';
import { HasPermissionDirective } from '@shared/directives';
import { ActionCode, ResourceCode } from '@shared/models';
import { isFocusLost } from '@shared/utils';
import { filter, switchMap } from 'rxjs/operators';

import { ToastService } from '../../../../../../../services/notifications';
import { GraphRagConfigurationDialog } from '../../../../../components/rag-configuration-dialog/graph-rag-configuration-dialog/graph-rag-configuration-dialog.component';
import { NaiveRagConfigurationDialog } from '../../../../../components/rag-configuration-dialog/naive-rag-configuration-dialog/naive-rag-configuration-dialog.component';
import { RagConfigurationDialogComponent } from '../../../../../components/rag-configuration-dialog/rag-configuration-dialog.component';
import { RAG_STATUS_CONFIG, RAG_TYPE_CONFIG } from '../../../../../constants/constants';
import { getIndexingUsageDetails, IndexingUsageDetail } from '../../../../../helpers/format-indexing-usage.util';
import { RagType } from '../../../../../models/base-rag.model';
import { CreateCollectionDtoResponse } from '../../../../../models/collection.model';
import { CollectionsStorageService } from '../../../../../services/collections-storage.service';
import { GraphRagDocumentsStorageService } from '../../../../../services/graph-rag-documents-storage.service';
import { NaiveRagDocumentsStorageService } from '../../../../../services/naive-rag-documents-storage.service';
import { RagDeleteRegistryService } from '../../../../../services/rag-delete-registry.service';

@Component({
    selector: 'app-collection-details-rags',
    templateUrl: 'collection-rags.component.html',
    styleUrls: ['./collection-rags.component.scss'],
    imports: [AppSvgIconComponent, MatTooltip, HasPermissionDirective],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class CollectionRagsComponent {
    private dialog = inject(Dialog);
    private destroyRef = inject(DestroyRef);
    private toast = inject(ToastService);
    private collectionsStorageService = inject(CollectionsStorageService);
    private confirmationService = inject(ConfirmationDialogService);
    private ragDeleteRegistry = inject(RagDeleteRegistryService);
    private naiveRagDocumentsStorage = inject(NaiveRagDocumentsStorageService);
    private graphRagDocumentsStorage = inject(GraphRagDocumentsStorageService);
    private readonly injector = inject(Injector);
    private readonly document = inject(DOCUMENT);

    collection = input.required<CreateCollectionDtoResponse>();
    /** The last RAG was deleted along with the focused button: the parent takes the focus instead. */
    readonly lastRagRemoved = output<void>();

    private readonly ragNameButtons = viewChildren<ElementRef<HTMLButtonElement>>('ragNameButton');

    protected readonly usageDetails = computed(() => {
        const detailsByType: Partial<Record<RagType, IndexingUsageDetail[]>> = {};
        for (const config of this.collection().rag_configurations) {
            detailsByType[config.rag_type] = getIndexingUsageDetails(config.indexing_usage);
        }
        return detailsByType;
    });
    /** RAG types whose usage details are open; each row toggles on its own, all start collapsed. */
    protected readonly expandedUsageTypes = signal<ReadonlySet<RagType>>(new Set());

    ragTypeConfig = RAG_TYPE_CONFIG;
    ragStatusConfig = RAG_STATUS_CONFIG;

    onConfigureRag(type: RagType): void {
        const ragConfigurations = this.collection().rag_configurations;
        const ragConfig = ragConfigurations.find((i) => i.rag_type === type);

        if (type === 'naive') {
            this.openRagConfigurationDialog(ragConfig!.rag_id, type, NaiveRagConfigurationDialog);
            return;
        }

        if (type === 'graph') {
            this.openRagConfigurationDialog(ragConfig!.rag_id, type, GraphRagConfigurationDialog);
            return;
        }
    }

    protected toggleUsage(type: RagType): void {
        this.expandedUsageTypes.update((expanded) => {
            const next = new Set(expanded);
            if (next.has(type)) {
                next.delete(type);
            } else {
                next.add(type);
            }
            return next;
        });
    }

    protected usageDetailsId(type: RagType): string {
        return `rag-usage-${this.collection().collection_id}-${type}`;
    }

    onDeleteRag(type: RagType, ragId: number): void {
        const ragName = this.ragTypeConfig[type].name;
        const index = this.collection().rag_configurations.findIndex((config) => config.rag_type === type);

        this.confirmationService
            .confirmDelete(ragName)
            .pipe(
                filter((result) => result === true),
                switchMap(() => this.ragDeleteRegistry.deleteRag(type, ragId)),
                switchMap(() =>
                    this.collectionsStorageService.getFullCollection(this.collection().collection_id, true)
                ),
                takeUntilDestroyed(this.destroyRef)
            )
            .subscribe(() => {
                this.toast.success('RAG deleted');
                if (type === 'naive') {
                    this.naiveRagDocumentsStorage.clear();
                } else if (type === 'graph') {
                    this.graphRagDocumentsStorage.clear();
                }
                this.keepFocusAfterRemoval(index);
            });
    }

    /** The deleted row takes its focused Delete button along: the focus moves to the RAG now in its place. */
    private keepFocusAfterRemoval(index: number): void {
        afterNextRender(
            () => {
                if (!isFocusLost(this.document)) return;
                const buttons = this.ragNameButtons();
                const next = buttons[Math.min(index, buttons.length - 1)];
                if (next) {
                    next.nativeElement.focus();
                } else {
                    this.lastRagRemoved.emit();
                }
            },
            { injector: this.injector }
        );
    }

    private openRagConfigurationDialog(
        ragId: number,
        ragType: RagType,
        dialogComponent: ComponentType<RagConfigurationDialogComponent>
    ): void {
        const collectionId = this.collection().collection_id;
        const dialog = this.dialog.open(dialogComponent, {
            width: 'calc(100vw - 2rem)',
            height: 'calc(100vh - 2rem)',
            data: { ragId, ragType, collectionId },
            disableClose: true,
        });

        dialog.closed
            .pipe(
                switchMap(() => this.collectionsStorageService.getFullCollection(collectionId, true)),
                takeUntilDestroyed(this.destroyRef)
            )
            .subscribe();
    }

    protected readonly ActionCode = ActionCode;
    protected readonly ResourceCode = ResourceCode;
}
