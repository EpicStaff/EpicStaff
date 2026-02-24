import {
    ChangeDetectionStrategy,
    Component,
    DestroyRef, effect,
    inject,
    model, OnChanges,
    OnInit,
    signal, SimpleChanges
} from "@angular/core";
import {
    AppIconComponent, SpinnerComponent, ValidationErrorsComponent, DragDropAreaComponent,
    ConfirmationDialogService
} from "@shared/components";
import {FormControl, FormsModule, ReactiveFormsModule, Validators} from "@angular/forms";
import {CreateCollectionDtoResponse} from "../../../../models/collection.model";
import {CollectionsStorageService} from "../../../../services/collections-storage.service";
import {catchError, debounceTime, distinctUntilChanged, finalize, switchMap} from "rxjs/operators";
import {takeUntilDestroyed} from "@angular/core/rxjs-interop";
import {EMPTY, filter, throwError} from "rxjs";
import {FILE_TYPES} from "../../../../constants/constants";
import {CollectionFilesComponent} from "./collection-files/collection-files.component";
import {CollectionRagsComponent} from "./collection-rags/collection-rags.component";
import {CollectionInfoComponent} from "./collection-info/collection-info.component";
import {DocumentsStorageService} from "../../../../services/documents-storage.service";
import {DisplayedListDocument} from "../../../../models/document.model";
import {FileListService} from "../../../../services/files-list.service";
import {ToastService} from "../../../../../../services/notifications";

@Component({
    selector: "app-collection-details",
    styleUrls: ["./collection-details.component.scss"],
    templateUrl: "./collection-details.component.html",
    imports: [
        AppIconComponent,
        FormsModule,
        ReactiveFormsModule,
        DragDropAreaComponent,
        CollectionFilesComponent,
        CollectionRagsComponent,
        CollectionInfoComponent,
        SpinnerComponent,
        ValidationErrorsComponent,
    ],
    changeDetection: ChangeDetectionStrategy.OnPush
})
export class CollectionDetailsComponent implements OnInit, OnChanges {
    private destroyRef = inject(DestroyRef);
    selectedCollectionId = model<number | null>(null);
    loadingCollection = signal<boolean>(false);
    loadingDocuments = signal<boolean>(false);
    fullCollection = signal<CreateCollectionDtoResponse | null>(null);
    documents = signal<DisplayedListDocument[]>([]);
    collectionName: FormControl = new FormControl("", [Validators.required, Validators.maxLength(255)]);

    private confirmationDialogService = inject(ConfirmationDialogService);
    private collectionsStorageService = inject(CollectionsStorageService);
    private documentsStorageService = inject(DocumentsStorageService);
    private fileListService = inject(FileListService);
    private toastService = inject(ToastService);

    constructor() {
        effect(() => {
            const collection = this.collectionsStorageService.fullCollections()
                .find((c) => c.collection_id === this.selectedCollectionId());

            if (collection) {
                this.fullCollection.set(collection);
                this.collectionName.setValue(this.fullCollection()?.collection_name, {emitEvent: false});
            }
        });

        effect(() => {
            const documents = this.documentsStorageService.documents()
                .filter(d => d.source_collection === this.selectedCollectionId())
                .map(d => ({
                    ...d,
                    isValidType: true,
                    isValidSize: true
                }))

            this.documents.set(documents);
        });
    }

    ngOnChanges(changes: SimpleChanges) {
        const id = changes['selectedCollectionId'].currentValue;
        if (!id) return;

        this.getCollectionData(id);
        this.getCollectionDocuments(id);
    }

    ngOnInit() {
        this.collectionName.valueChanges.pipe(
            takeUntilDestroyed(this.destroyRef),
            debounceTime(400),
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
            }),
        ).subscribe(() => this.toastService.success('Collection Updated'));
    }

    private getCollectionData(id: number): void {
        this.loadingCollection.set(true);
        this.collectionsStorageService.getFullCollection(id)
            .pipe(
                takeUntilDestroyed(this.destroyRef),
                catchError((error) => {
                    this.toastService.error('Failed to get collection data')
                    return throwError(() => error)
                }),
                finalize(() => this.loadingCollection.set(false)),
            )
            .subscribe();
    }

    private getCollectionDocuments(id: number): void {
        this.loadingDocuments.set(true);
        this.documentsStorageService.getDocumentsByCollectionId(id)
            .pipe(
                takeUntilDestroyed(this.destroyRef),
                finalize(() => this.loadingDocuments.set(false)),
            )
            .subscribe();
    }

    onCollectionDelete(): void {
        const collection = this.fullCollection();
        if (collection) {
            this.confirmationDialogService
                .confirmDelete(collection.collection_name)
                .pipe(takeUntilDestroyed(this.destroyRef))
                .subscribe((result) => {
                    if (result === true) {
                        this.collectionsStorageService.deleteCollectionById(collection.collection_id)
                            .pipe(takeUntilDestroyed(this.destroyRef))
                            .subscribe({
                                next: () => {
                                    this.selectedCollectionId.set(null);
                                    this.fullCollection.set(null);
                                },
                                error: () => this.toastService.error('Collection Delete failed'),
                            });
                    }
                });
        }
    }

    onFilesDropped(files: FileList) {
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
        if (!toUpload.length) {return;}
        // 5: upload filtered and valid files to backend
        this.documentsStorageService.uploadDocuments(collectionId, toUpload)
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe();
    }

    onFileSelect(event: Event): void {
        const input = event.target as HTMLInputElement;
        if (input.files) {
            this.onFilesDropped(input.files);
            input.value = '';
        }
    }

    protected readonly FILE_TYPES = FILE_TYPES;
}
