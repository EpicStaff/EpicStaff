import { UpperCasePipe } from '@angular/common';
import {
    AfterViewInit,
    ChangeDetectionStrategy,
    Component,
    DestroyRef,
    effect,
    ElementRef,
    inject,
    input,
    model,
    OnInit,
    signal,
    untracked,
    viewChild,
} from '@angular/core';
import { takeUntilDestroyed, toObservable, toSignal } from '@angular/core/rxjs-interop';
import { FormControl, ReactiveFormsModule, Validators } from '@angular/forms';
import {
    BlobPreviewComponent,
    FileUploaderComponent,
    HelpTooltipComponent,
    ValidationErrorsComponent,
} from '@shared/components';
import { HasPermissionDirective } from '@shared/directives';
import { notWhitespaceValidator } from '@shared/form-validators';
import { ActionCode, ResourceCode } from '@shared/models';
import {
    catchError,
    debounceTime,
    distinctUntilChanged,
    EMPTY,
    filter,
    map,
    Observable,
    of,
    startWith,
    switchMap,
} from 'rxjs';

import { ToastService } from '../../../../../../../services/notifications';
import { FILE_TYPES } from '../../../../../constants/constants';
import { CreateCollectionDtoResponse } from '../../../../../models/collection.model';
import { DisplayedListDocument } from '../../../../../models/document.model';
import { CollectionsStorageService } from '../../../../../services/collections-storage.service';
import { DocumentsApiService } from '../../../../../services/documents-api.service';
import { DocumentsStorageService } from '../../../../../services/documents-storage.service';
import { FileListService } from '../../../../../services/files-list.service';
import { FilesListComponent } from './files-list/files-list.component';

interface PreviewState {
    blob: Blob | null;
    fileName: string;
}

@Component({
    selector: 'app-step-upload-files',
    templateUrl: './step-upload-files.component.html',
    styleUrls: ['./step-upload-files.component.scss'],
    imports: [
        HelpTooltipComponent,
        ReactiveFormsModule,
        FileUploaderComponent,
        FilesListComponent,
        BlobPreviewComponent,
        UpperCasePipe,
        ValidationErrorsComponent,
        HasPermissionDirective,
    ],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class StepUploadFilesComponent implements OnInit, AfterViewInit {
    private destroyRef = inject(DestroyRef);
    private collectionsStorageService = inject(CollectionsStorageService);
    private documentsStorageService = inject(DocumentsStorageService);
    private documentsApiService = inject(DocumentsApiService);
    private fileListService = inject(FileListService);
    private readonly toastService = inject(ToastService);

    collectionName: FormControl = new FormControl('', [
        Validators.required,
        notWhitespaceValidator(),
        Validators.maxLength(255),
    ]);
    description: FormControl = new FormControl('', [Validators.maxLength(250)]);
    private readonly descriptionTa = viewChild<ElementRef<HTMLTextAreaElement>>('descriptionTa');
    collection = input.required<CreateCollectionDtoResponse>();
    documents = model<DisplayedListDocument[]>([]);
    initialDocumentId = input<number | undefined>(undefined);
    selectedDocument = signal<DisplayedListDocument | null>(null);

    previewState = toSignal(
        toObservable(this.selectedDocument).pipe(
            switchMap((doc): Observable<PreviewState> => {
                if (!doc?.document_id) return of({ blob: null, fileName: '' });
                return this.documentsApiService.previewDocumentBlob(doc.document_id).pipe(
                    map((blob) => ({ blob, fileName: doc.file_name })),
                    startWith({ blob: null, fileName: doc.file_name }),
                    catchError(() => of({ blob: null, fileName: doc.file_name }))
                );
            })
        ),
        { initialValue: { blob: null, fileName: '' } as PreviewState }
    );

    constructor() {
        effect(() => {
            const id = this.initialDocumentId();
            if (!id || this.selectedDocument()) return;
            const doc = this.documents().find((d) => d.document_id === id);
            if (doc) this.selectedDocument.set(doc);
        });

        effect(() => {
            const collectionId = this.collection().collection_id;
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
    }

    ngOnInit() {
        this.collectionName.setValue(this.collection().collection_name, { emitEvent: false });
        this.description.setValue(this.collection().description ?? '', { emitEvent: false });

        if (this.collection().document_count > 0) {
            this.getCollectionDocuments(this.collection().collection_id);
        }

        this.subscribeToCollectionName();
        this.subscribeToDescription();
    }

    ngAfterViewInit(): void {
        const el = this.descriptionTa()?.nativeElement;
        if (el) this.autoGrow(el);
    }

    autoGrow(textarea: HTMLTextAreaElement): void {
        const maxPx = 128;
        textarea.style.height = 'auto';
        const full = textarea.scrollHeight;
        textarea.style.height = `${Math.min(full, maxPx)}px`;
        textarea.style.overflowY = full > maxPx ? 'auto' : 'hidden';
    }

    private getCollectionDocuments(id: number): void {
        this.documentsStorageService
            .getDocumentsByCollectionId(id)
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe();
    }

    private subscribeToCollectionName() {
        this.collectionName?.valueChanges
            .pipe(
                takeUntilDestroyed(this.destroyRef),
                debounceTime(400),
                distinctUntilChanged(),
                filter(() => this.collectionName.valid),
                switchMap((collection_name: string) => {
                    const id = this.collection().collection_id;
                    const body = { collection_name };

                    return this.collectionsStorageService.updateCollectionById(id, body).pipe(
                        catchError(() => {
                            this.toastService.error('Collection Update failed');
                            return EMPTY;
                        })
                    );
                })
            )
            .subscribe(() => this.toastService.success('Collection Updated'));
    }

    private subscribeToDescription() {
        this.description.valueChanges
            .pipe(
                takeUntilDestroyed(this.destroyRef),
                debounceTime(400),
                map((description: string) => description.trim()),
                distinctUntilChanged(),
                filter(() => this.description.valid),
                switchMap((description: string) => {
                    const id = this.collection().collection_id;
                    return this.collectionsStorageService.updateCollectionById(id, { description }).pipe(
                        catchError(() => {
                            this.toastService.error('Collection Update failed');
                            return EMPTY;
                        })
                    );
                })
            )
            .subscribe(() => this.toastService.success('Collection Updated'));
    }

    onFilesUpload(files: FileList): void {
        const collectionId = this.collection().collection_id;
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
        // 5: upload filtered and valid files to backend (no takeUntilDestroyed to keep uploading on dialog close/step switch)
        const placeholders = transformed.filter((d) => d.isValidType && d.isValidSize);
        this.documentsStorageService.uploadDocuments(collectionId, toUpload, placeholders).subscribe();
    }

    protected readonly FILE_TYPES = FILE_TYPES;
    protected readonly ActionCode = ActionCode;
    protected readonly ResourceCode = ResourceCode;
}
