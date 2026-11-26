import { Dialog } from '@angular/cdk/dialog';
import { inject, Injectable, signal } from '@angular/core';
import { finalize, switchMap } from 'rxjs/operators';

import { ToastService } from '../../../services/notifications';
import { CreateCollectionDialogComponent } from '../components/create-collection-dialog/create-collection-dialog.component';
import { extractStorageFileIds } from '../helpers/storage-import.util';
import { StorageImportCandidate } from '../models/document.model';
import { CollectionsStorageService } from './collections-storage.service';
import { DocumentsStorageService } from './documents-storage.service';
import { FileListService } from './files-list.service';

/**
 * Starts a new knowledge collection: creates an empty one, selects it and opens the Create New Collection
 * wizard on it, then reloads the collection once the wizard closes.
 *
 * The drop variants also put the dropped storage items or files into the new collection, so the wizard's
 * Upload files step opens with them. Nothing is created when none of them could be added.
 *
 * A root service, so a creation, its import or upload and the wizard all outlive the page that started them.
 */
@Injectable({ providedIn: 'root' })
export class CollectionCreationService {
    private readonly creatingSignal = signal<boolean>(false);
    /** The create request is in flight; another creation is refused until it settles. */
    readonly isCreating = this.creatingSignal.asReadonly();

    private readonly dialog = inject(Dialog);
    private readonly collectionsStorage = inject(CollectionsStorageService);
    private readonly documentsStorage = inject(DocumentsStorageService);
    private readonly fileListService = inject(FileListService);
    private readonly toastService = inject(ToastService);

    createCollection(): void {
        this.start(() => undefined);
    }

    /** Toasts and reports what it could not add the way an import into an existing collection does. */
    createCollectionFromStorage(items: StorageImportCandidate[]): void {
        if (extractStorageFileIds(items).storageFileIds.length === 0) {
            this.toastService.error('None of the selected items could be added');
            return;
        }
        // Fire and forget: DocumentsStorageService subscribes to the import itself and toasts its outcome.
        this.start((collectionId) => {
            this.documentsStorage.importFromStorage(collectionId, items);
        });
    }

    /** Same-name files are added once; files of a type or size a collection does not take are skipped. */
    createCollectionFromFiles(files: FileList): void {
        const unique = this.fileListService.filterDuplicatesByName(files, []);
        const toUpload = this.fileListService.filterValidFiles(unique);
        if (toUpload.length === 0) {
            this.toastService.error('None of the dropped files could be added: unsupported type or too large');
            return;
        }
        const skippedCount = unique.length - toUpload.length;
        if (skippedCount > 0) {
            this.toastService.warning(`${skippedCount} file(s) skipped: unsupported type or too large`);
        }
        this.start((collectionId) => {
            const placeholders = this.fileListService.transformFilesToDisplayedDocuments(toUpload, collectionId);
            this.documentsStorage.uploadDocuments(collectionId, toUpload, placeholders).subscribe();
        });
    }

    private start(fill: (collectionId: number) => void): void {
        if (this.creatingSignal()) return;
        this.creatingSignal.set(true);
        this.collectionsStorage
            .createCollection()
            .pipe(finalize(() => this.creatingSignal.set(false)))
            .subscribe({
                next: ({ collection_id }) => {
                    if (!collection_id) return;
                    this.documentsStorage.registerNewCollection(collection_id);
                    this.collectionsStorage.setSelectedCollectionId(collection_id);
                    fill(collection_id);
                    this.openWizard(collection_id);
                },
                error: () => this.toastService.error('Failed to create collection'),
            });
    }

    private openWizard(collectionId: number): void {
        this.dialog
            .open(CreateCollectionDialogComponent, {
                width: 'calc(100vw - 2rem)',
                height: 'calc(100vh - 2rem)',
                data: { collection_id: collectionId },
                disableClose: true,
            })
            .closed.pipe(switchMap(() => this.collectionsStorage.getFullCollection(collectionId, true)))
            .subscribe({
                error: () => this.toastService.error('Failed to get collection data'),
            });
    }
}
