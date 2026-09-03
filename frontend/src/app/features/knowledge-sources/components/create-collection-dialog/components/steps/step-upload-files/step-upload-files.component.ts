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
    viewChild,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { FormControl, ReactiveFormsModule, Validators } from '@angular/forms';
import { FileUploaderComponent, HelpTooltipComponent, ValidationErrorsComponent } from '@shared/components';
import { HasPermissionDirective } from '@shared/directives';
import { notWhitespaceValidator } from '@shared/form-validators';
import { ActionCode, ResourceCode } from '@shared/models';
import { EMPTY, filter } from 'rxjs';
import { catchError, debounceTime, distinctUntilChanged, map, switchMap } from 'rxjs/operators';

import { ToastService } from '../../../../../../../services/notifications';
import { FILE_TYPES } from '../../../../../constants/constants';
import { CreateCollectionDtoResponse } from '../../../../../models/collection.model';
import { DisplayedListDocument } from '../../../../../models/document.model';
import { CollectionsStorageService } from '../../../../../services/collections-storage.service';
import { DocumentsStorageService } from '../../../../../services/documents-storage.service';
import { FileListService } from '../../../../../services/files-list.service';
import { FilePreviewComponent } from './file-preview/file-preview.component';
import { FilesListComponent } from './files-list/files-list.component';

@Component({
    selector: 'app-step-upload-files',
    templateUrl: './step-upload-files.component.html',
    styleUrls: ['./step-upload-files.component.scss'],
    imports: [
        HelpTooltipComponent,
        ReactiveFormsModule,
        FileUploaderComponent,
        FilesListComponent,
        FilePreviewComponent,
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

    constructor() {
        effect(() => {
            const documents = this.documentsStorageService
                .documents()
                .filter((d) => d.source_collection === this.collection().collection_id)
                .map((d) => ({
                    ...d,
                    isValidType: true,
                    isValidSize: true,
                }));

            this.documents.set(documents);
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
        // 5: upload filtered and valid files to backend
        this.documentsStorageService
            .uploadDocuments(collectionId, toUpload)
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe();
    }

    protected readonly FILE_TYPES = FILE_TYPES;
    protected readonly ActionCode = ActionCode;
    protected readonly ResourceCode = ResourceCode;
}
