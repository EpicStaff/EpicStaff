import { Dialog } from '@angular/cdk/dialog';
import {
    ChangeDetectionStrategy,
    Component,
    computed,
    DestroyRef,
    effect,
    inject,
    linkedSignal,
    signal,
    untracked,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { MatTooltipModule } from '@angular/material/tooltip';
import {
    AppSvgIconComponent,
    ConfirmationDialogService,
    DragDropAreaComponent,
    SelectComponent,
    SelectItem,
    SpinnerComponent,
} from '@shared/components';
import { HasPermissionDirective } from '@shared/directives';
import { ActionCode, ResourceCode } from '@shared/models';
import { filter, switchMap, throwError } from 'rxjs';
import { catchError, finalize } from 'rxjs/operators';

import { PermissionsService } from '../../../../../../services/auth/permissions.service';
import { ToastService } from '../../../../../../services/notifications';
import { CopyCollectionFilesDialogComponent } from '../../../../components/copy-collection-files-dialog/copy-collection-files-dialog.component';
import { CreateCollectionDialogComponent } from '../../../../components/create-collection-dialog/create-collection-dialog.component';
import { FILE_TYPES } from '../../../../constants/constants';
import { collectFileTypes, isStoredDocument } from '../../../../helpers/collection-stats.util';
import { CreateCollectionDtoResponse } from '../../../../models/collection.model';
import { DisplayedListDocument } from '../../../../models/document.model';
import { CollectionDetailsDialogService } from '../../../../services/collection-details-dialog.service';
import { CollectionsStorageService } from '../../../../services/collections-storage.service';
import { DocumentsApiService } from '../../../../services/documents-api.service';
import { DocumentsStorageService } from '../../../../services/documents-storage.service';
import { FileListService } from '../../../../services/files-list.service';
import { CollectionBasicsComponent } from './collection-basics/collection-basics.component';
import { CollectionFilesComponent } from './collection-files/collection-files.component';
import { CollectionRagsComponent } from './collection-rags/collection-rags.component';

/** The "Filter by type" option that shows every type; selecting it brings the placeholder back. */
const ALL_FILE_TYPES_ITEM: SelectItem<string | null> = { name: 'All types', value: null };

@Component({
    selector: 'app-collection-details',
    styleUrls: ['./collection-details.component.scss'],
    templateUrl: './collection-details.component.html',
    imports: [
        DragDropAreaComponent,
        CollectionBasicsComponent,
        CollectionFilesComponent,
        CollectionRagsComponent,
        SelectComponent,
        SpinnerComponent,
        AppSvgIconComponent,
        MatTooltipModule,
        HasPermissionDirective,
    ],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class CollectionDetailsComponent {
    private confirmationDialogService = inject(ConfirmationDialogService);
    private collectionsStorageService = inject(CollectionsStorageService);
    private documentsStorageService = inject(DocumentsStorageService);
    private documentsApiService = inject(DocumentsApiService);
    private fileListService = inject(FileListService);
    private toastService = inject(ToastService);
    private permissionsService = inject(PermissionsService);
    private collectionDetailsDialog = inject(CollectionDetailsDialogService);
    private dialog = inject(Dialog);
    private destroyRef = inject(DestroyRef);

    loadingCollection = signal<boolean>(false);
    loadingDocuments = signal<boolean>(false);
    fullCollection = signal<CreateCollectionDtoResponse | null>(null);
    documents = signal<DisplayedListDocument[]>([]);
    selectedCollectionId = this.collectionsStorageService.selectedCollectionId;

    private readonly fileTypes = computed(() => collectFileTypes(this.documents()));
    /** The "Filter by type" choice; cleared once the collection has no files of that type any more. */
    protected readonly activeFileType = linkedSignal<string[], string | null>({
        source: this.fileTypes,
        computation: (fileTypes, previous) =>
            previous?.value && fileTypes.includes(previous.value) ? previous.value : null,
    });
    protected readonly fileTypeItems = computed<SelectItem<string | null>[]>(() => [
        ALL_FILE_TYPES_ITEM,
        ...this.fileTypes().map((fileType) => ({ name: `.${fileType}`, value: fileType })),
    ]);

    constructor() {
        effect(() => {
            const selectedId = this.selectedCollectionId();
            const collection = this.collectionsStorageService
                .fullCollections()
                .find((c) => c.collection_id === selectedId);

            if (collection) {
                this.fullCollection.set(collection);
            }
        });

        effect(() => {
            const collectionId = this.selectedCollectionId();
            const realDocs = this.documentsStorageService
                .documents()
                .filter((d) => d.source_collection === collectionId)
                .map((d) => ({
                    ...d,
                    isValidType: true,
                    isValidSize: true,
                }));
            const uploading = this.documentsStorageService
                .uploadingDocuments()
                .filter((d) => d.source_collection === collectionId);

            // Invalid dropped files (wrong type/size) never reach uploadDocuments, so they
            // only ever exist in this signal's own prior state — carry them forward or this
            // rebuild (re-triggered by any upload anywhere finishing, not just this collection's)
            // silently wipes them instead of leaving them visible with their error state.
            const invalidLocal = untracked(() => this.documents().filter((d) => !d.isValidType || !d.isValidSize));

            this.documents.set([...realDocs, ...uploading, ...invalidLocal]);
        });

        effect(() => {
            const id = this.selectedCollectionId();
            if (!id) return;
            untracked(() => {
                // Types differ per collection, so every collection opens unfiltered.
                this.activeFileType.set(null);
                this.getCollectionData(id);
                this.getCollectionDocuments(id);
            });
        });
    }

    protected onFileTypeChange(fileType: unknown): void {
        this.activeFileType.set(typeof fileType === 'string' ? fileType : null);
    }

    protected openDetails(trigger: HTMLElement): void {
        const collection = this.fullCollection();
        if (!collection) return;
        this.collectionDetailsDialog.open(collection, this.documents(), trigger);
    }

    private getCollectionData(id: number): void {
        this.loadingCollection.set(true);
        this.collectionsStorageService
            .getFullCollection(id)
            .pipe(
                takeUntilDestroyed(this.destroyRef),
                catchError((error) => {
                    this.toastService.error('Failed to get collection data');
                    return throwError(() => error);
                }),
                finalize(() => this.loadingCollection.set(false))
            )
            .subscribe();
    }

    private getCollectionDocuments(id: number): void {
        this.loadingDocuments.set(true);
        this.documentsStorageService
            .getDocumentsByCollectionId(id)
            .pipe(
                takeUntilDestroyed(this.destroyRef),
                finalize(() => this.loadingDocuments.set(false))
            )
            .subscribe();
    }

    onCollectionDelete(): void {
        const collection = this.fullCollection();
        if (!collection) return;

        const deletedId = collection.collection_id;

        this.confirmationDialogService
            .confirmDelete(collection.collection_name)
            .pipe(
                filter((result) => result === true),
                switchMap(() => this.collectionsStorageService.deleteCollectionById(deletedId)),
                takeUntilDestroyed(this.destroyRef)
            )
            .subscribe({
                next: () => {
                    this.toastService.success('Collection deleted successfully');
                    if (this.selectedCollectionId() === deletedId) {
                        this.collectionsStorageService.setSelectedCollectionId(null);
                        this.fullCollection.set(null);
                    }
                },
                error: () => this.toastService.error('Collection delete failed'),
            });
    }

    onFilesDropped(files: FileList) {
        if (!this.permissionsService.can(ResourceCode.KnowledgeSources, ActionCode.Create)) return;
        const collectionId = this.fullCollection()?.collection_id;
        if (!collectionId) return;
        // 1: filter duplicates by file name
        const filteredByName = this.fileListService.filterDuplicatesByName(files, this.documents());
        // 2: transform File[] to DisplayedListDocument[]
        const transformed = this.fileListService.transformFilesToDisplayedDocuments(filteredByName, collectionId);
        // 3: display both valid and invalid files
        this.documents.update((d) => [...d, ...transformed]);
        // 4: filter valid files for upload to backend
        const toUpload = this.fileListService.filterValidFiles(filteredByName);
        if (!toUpload.length) {
            return;
        }
        // 5: upload filtered and valid files to backend (no takeUntilDestroyed to keep uploading on page switch)
        const placeholders = transformed.filter((d) => d.isValidType && d.isValidSize);
        this.documentsStorageService.uploadDocuments(collectionId, toUpload, placeholders).subscribe();
    }

    onFileSelect(event: Event): void {
        const input = event.target as HTMLInputElement;
        if (input.files) {
            this.onFilesDropped(input.files);
            input.value = '';
        }
    }

    openCopyFilesDialog(): void {
        const collection = this.fullCollection();
        if (!collection) return;

        const documents = this.documentsStorageService
            .documents()
            .filter((d) => d.source_collection === collection.collection_id);

        this.dialog.open(CopyCollectionFilesDialogComponent, {
            data: {
                sourceCollectionId: collection.collection_id,
                documents,
                allCollections: this.collectionsStorageService.collections(),
            },
        });
    }

    onFilePreview(id: number): void {
        const collection = this.fullCollection();
        if (!collection) return;
        this.dialog.open(CreateCollectionDialogComponent, {
            width: 'calc(100vw - 2rem)',
            height: 'calc(100vh - 2rem)',
            data: { collection_id: collection.collection_id, isUpdate: true, initialDocumentId: id },
            disableClose: true,
        });
    }

    onFileDownload(id: number): void {
        const doc = this.documents().find((d) => d.document_id === id);
        if (!doc) return;

        this.downloadDocuments([id], doc.file_name);
    }

    /** Every stored file of the collection, whatever "Filter by type" shows — as the tooltip says. */
    downloadAllFiles(): void {
        const stored = this.documents().filter(isStoredDocument);
        const ids = stored.map((d) => d.document_id);
        if (!ids.length) return;

        const fileName = ids.length === 1 ? stored[0].file_name : 'documents.zip';

        this.downloadDocuments(ids, fileName);
    }

    private downloadDocuments(ids: number[], fileName: string): void {
        this.documentsApiService
            .downloadDocuments(ids)
            // do not destroy the subscription to keep downloading on page switching (EST-3085)
            .subscribe((blob) => this.triggerDownload(blob, fileName));
    }

    private triggerDownload(blob: Blob, fileName: string): void {
        const url = URL.createObjectURL(blob);

        const a = document.createElement('a');
        a.href = url;
        a.download = fileName;
        a.click();

        URL.revokeObjectURL(url);
    }

    openCreateCollectionModal(): void {
        const collection = this.fullCollection();

        if (!collection) return;

        const dialog = this.dialog.open(CreateCollectionDialogComponent, {
            width: 'calc(100vw - 2rem)',
            height: 'calc(100vh - 2rem)',
            data: { collection_id: collection.collection_id, isUpdate: true },
            disableClose: true,
        });

        dialog.closed
            .pipe(
                takeUntilDestroyed(this.destroyRef),
                switchMap(() => {
                    return this.collectionsStorageService.getFullCollection(collection.collection_id, true);
                }),
                catchError((error) => {
                    this.toastService.error('Failed to get collection data');
                    return throwError(() => error);
                })
            )
            .subscribe();
    }

    protected readonly FILE_TYPES = FILE_TYPES;
    protected readonly ResourceCode = ResourceCode;
    protected readonly ActionCode = ActionCode;
}
