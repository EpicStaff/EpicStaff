import { Dialog } from '@angular/cdk/dialog';
import {
    ChangeDetectionStrategy,
    Component,
    DestroyRef,
    effect,
    inject,
    OnInit,
    signal,
    untracked,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { FormControl, FormsModule, ReactiveFormsModule, Validators } from '@angular/forms';
import { MatTooltipModule } from '@angular/material/tooltip';
import {
    AppSvgIconComponent,
    ConfirmationDialogService,
    DragDropAreaComponent,
    SpinnerComponent,
    ValidationErrorsComponent,
} from '@shared/components';
import { HasPermissionDirective } from '@shared/directives';
import { notWhitespaceValidator } from '@shared/form-validators';
import { ActionCode, ResourceCode } from '@shared/models';
import { EMPTY, filter, throwError } from 'rxjs';
import { catchError, debounceTime, distinctUntilChanged, finalize, switchMap } from 'rxjs/operators';

import { PermissionsService } from '../../../../../../services/auth/permissions.service';
import { ToastService } from '../../../../../../services/notifications';
import { CopyCollectionFilesDialogComponent } from '../../../../components/copy-collection-files-dialog/copy-collection-files-dialog.component';
import { CreateCollectionDialogComponent } from '../../../../components/create-collection-dialog/create-collection-dialog.component';
import { FILE_TYPES } from '../../../../constants/constants';
import { CreateCollectionDtoResponse } from '../../../../models/collection.model';
import { DisplayedListDocument } from '../../../../models/document.model';
import { CollectionsStorageService } from '../../../../services/collections-storage.service';
import { DocumentsApiService } from '../../../../services/documents-api.service';
import { DocumentsStorageService } from '../../../../services/documents-storage.service';
import { FileListService } from '../../../../services/files-list.service';
import { CollectionFilesComponent } from './collection-files/collection-files.component';
import { CollectionInfoComponent } from './collection-info/collection-info.component';
import { CollectionRagsComponent } from './collection-rags/collection-rags.component';

@Component({
    selector: 'app-collection-details',
    styleUrls: ['./collection-details.component.scss'],
    templateUrl: './collection-details.component.html',
    imports: [
        FormsModule,
        ReactiveFormsModule,
        DragDropAreaComponent,
        CollectionFilesComponent,
        CollectionRagsComponent,
        CollectionInfoComponent,
        SpinnerComponent,
        ValidationErrorsComponent,
        AppSvgIconComponent,
        MatTooltipModule,
        HasPermissionDirective,
    ],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class CollectionDetailsComponent implements OnInit {
    private confirmationDialogService = inject(ConfirmationDialogService);
    private collectionsStorageService = inject(CollectionsStorageService);
    private documentsStorageService = inject(DocumentsStorageService);
    private documentsApiService = inject(DocumentsApiService);
    private fileListService = inject(FileListService);
    private toastService = inject(ToastService);
    private permissionsService = inject(PermissionsService);
    private dialog = inject(Dialog);
    private destroyRef = inject(DestroyRef);

    loadingCollection = signal<boolean>(false);
    loadingDocuments = signal<boolean>(false);
    fullCollection = signal<CreateCollectionDtoResponse | null>(null);
    documents = signal<DisplayedListDocument[]>([]);
    selectedCollectionId = this.collectionsStorageService.selectedCollectionId;

    readonly descriptionSaveFailedTick = signal<number>(0);

    collectionName: FormControl = new FormControl('', [
        Validators.required,
        notWhitespaceValidator(),
        Validators.maxLength(255),
    ]);

    private lastInitializedCollectionId: number | null = null;

    constructor() {
        // Structural *appHasPermission would remove the input (and the name it
        // displays) entirely for view-only users — disable it instead so the name
        // stays visible, just not editable.
        if (!this.permissionsService.can(ResourceCode.KnowledgeSources, ActionCode.Update)) {
            this.collectionName.disable();
        }

        effect(() => {
            const selectedId = this.selectedCollectionId();
            const collection = this.collectionsStorageService
                .fullCollections()
                .find((c) => c.collection_id === selectedId);

            if (collection) {
                this.fullCollection.set(collection);
                if (this.lastInitializedCollectionId !== collection.collection_id) {
                    this.collectionName.setValue(collection.collection_name, { emitEvent: false });
                    this.lastInitializedCollectionId = collection.collection_id;
                }
            } else {
                this.lastInitializedCollectionId = null;
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
                this.getCollectionData(id);
                this.getCollectionDocuments(id);
            });
        });
    }

    ngOnInit() {
        this.collectionName.valueChanges
            .pipe(
                takeUntilDestroyed(this.destroyRef),
                debounceTime(600),
                distinctUntilChanged(),
                filter(() => this.collectionName.valid),
                filter(() => !!this.fullCollection()),
                switchMap((collection_name: string) => {
                    const id = this.fullCollection()!.collection_id;
                    return this.collectionsStorageService.updateCollectionById(id, { collection_name }).pipe(
                        catchError(() => {
                            this.toastService.error('Collection Update failed');
                            return EMPTY;
                        })
                    );
                })
            )
            .subscribe(() => this.toastService.success('Collection Updated'));
    }

    onDescriptionSave(description: string): void {
        const collection = this.fullCollection();
        if (!collection) return;
        this.collectionsStorageService
            .updateCollectionById(collection.collection_id, { description })
            .pipe(
                takeUntilDestroyed(this.destroyRef),
                catchError(() => {
                    this.toastService.error('Collection Update failed');
                    this.descriptionSaveFailedTick.update((n) => n + 1);
                    return EMPTY;
                })
            )
            .subscribe(() => this.toastService.success('Collection Updated'));
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
        if (!this.permissionsService.can(ResourceCode.KnowledgeSources, ActionCode.Update)) return;
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

    downloadAllFiles(): void {
        const documents = this.documents();
        const ids = documents.filter((d) => d.document_id).map((d) => d.document_id!);
        if (!ids.length) return;

        const fileName = ids.length === 1 ? documents[0].file_name : 'documents.zip';

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
