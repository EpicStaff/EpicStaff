import { DIALOG_DATA, DialogRef } from '@angular/cdk/dialog';
import { hasModifierKey } from '@angular/cdk/keycodes';
import { OverlayModule } from '@angular/cdk/overlay';
import { HttpErrorResponse } from '@angular/common/http';
import { ChangeDetectionStrategy, Component, computed, DestroyRef, HostListener, inject, signal } from '@angular/core';
import { takeUntilDestroyed, toSignal } from '@angular/core/rxjs-interop';
import { FormsModule } from '@angular/forms';
import { MatTooltipModule } from '@angular/material/tooltip';
import {
    AppSvgIconComponent,
    ConfirmationDialogService,
    DragDropAreaComponent,
    FileUploaderComponent,
    HelpTooltipComponent,
    Spinner2Component,
} from '@shared/components';
import { extractHttpErrorMessage } from '@shared/utils';
import { catchError, EMPTY, merge, Observable, of, switchMap } from 'rxjs';
import { filter, map, tap, toArray } from 'rxjs/operators';

import { ToastService } from '../../../../services/notifications';
import { FileSizePipe } from '../../../../shared/pipes/file-size.pipe';
import { StorageUploadBatchResult } from '../../models/storage.models';
import { StorageApiService } from '../../services/storage-api.service';
import { StorageUploadService, toUploadBatchResult } from '../../services/storage-upload.service';
import { flattenFolderNodes, StorageFolderNode, toFolderNodes } from '../../utils/storage-tree.utils';
import { CLOSE_DURING_UPLOAD_CONFIRMATION } from '../../utils/upload-dialog.constants';
import { describeUploadError, describeUploadFailures, UploadErrorDescription } from '../../utils/upload-error.utils';
import { describeUploadLimits, isArchiveForLimits, usableUploadLimits } from '../../utils/upload-limits.utils';

export interface CreateFolderDialogData {
    /** Pre-fill the destination folder path */
    folderPath?: string;
}

export interface AddFilesPayload {
    /** Full destination path: destinationPath + optional subfolder name */
    targetPath: string;
    files: File[];
    /** True when no files selected — only mkdir should be called */
    mkdirOnly: boolean;
}

export interface CreateFolderDialogResult {
    type: 'mkdir' | 'upload';
    path?: string;
    count?: number;
}

@Component({
    selector: 'app-create-folder-dialog',
    imports: [
        FormsModule,
        AppSvgIconComponent,
        HelpTooltipComponent,
        Spinner2Component,
        MatTooltipModule,
        OverlayModule,
        FileUploaderComponent,
        DragDropAreaComponent,
        FileSizePipe,
    ],
    templateUrl: './create-folder-dialog.component.html',
    styleUrls: ['./create-folder-dialog.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class CreateFolderDialogComponent {
    private dialogRef = inject(DialogRef<CreateFolderDialogResult | undefined>);
    private data: CreateFolderDialogData = inject(DIALOG_DATA, { optional: true }) ?? {};
    private storageApiService = inject(StorageApiService);
    private storageUploadService = inject(StorageUploadService);
    private confirmationDialogService = inject(ConfirmationDialogService);
    private toastService = inject(ToastService);
    private destroyRef = inject(DestroyRef);

    private static readonly BLOCKED_EXTENSIONS = new Set([
        'exe',
        'msi',
        'com',
        'scr',
        'pif',
        'bat',
        'cmd',
        'vbs',
        'vbe',
        'wsh',
        'wsf',
        'ps1',
        'psm1',
        'psd1',
        'sh',
        'bash',
        'csh',
        'ksh',
        'zsh',
        'app',
        'command',
        'elf',
        'jar',
        'war',
        'ear',
        'dll',
        'so',
        'dylib',
        'rar',
        '7z',
    ]);

    readonly folderName = signal('');
    readonly files = signal<File[]>([]);
    readonly viewAllOpen = signal(false);

    toggleViewAll(): void {
        this.viewAllOpen.update((v) => !v);
    }

    closeViewAll(): void {
        this.viewAllOpen.set(false);
    }

    // Destination folder dropdown
    readonly dropdownOpen = signal(false);
    readonly searchQuery = signal('');
    readonly rootNodes = signal<StorageFolderNode[]>([]);
    readonly isLoadingRoot = signal(true);
    readonly selectedPath = signal<string>('');

    private readonly allNodes = signal<StorageFolderNode[]>([]);

    readonly visibleNodes = computed(() => {
        const query = this.searchQuery().toLowerCase().trim();
        const roots = this.rootNodes();
        if (query) {
            const filtered = this.allNodes().filter((n) => n.name.toLowerCase().includes(query));
            const minLevel = filtered.reduce((min, n) => Math.min(min, n.level), Infinity);
            return filtered.map((n) => ({ ...n, level: n.level - minLevel }));
        }
        return this.buildVisible(roots);
    });

    get selectedFolderLabel(): string {
        const path = this.selectedPath();
        return path ? `/${path}` : '/';
    }

    readonly isUploading = signal(false);
    /** From Confirm until the attempt settles: the overwrite check, then the upload itself. */
    private readonly confirmInFlight = signal(false);
    /** New files would not be part of the running attempt, and a successful one closes the dialog without them. */
    protected readonly isAddingFilesBlocked = computed(() => this.isUploading() || this.confirmInFlight());
    /** Files uploaded so far, recorded per file so closing mid-upload still reports them. */
    private readonly uploadedFiles = new Set<File>();
    /** The "close during upload" question is open. */
    private isConfirmingClose = false;
    /** The upload finished while that question was open; close once it is answered. */
    private closeDeferredByConfirmation = false;
    /** Maps filename → why the server did not take that file on the last attempt */
    readonly fileServerErrors = signal<Map<string, UploadErrorDescription>>(new Map());
    readonly hasBlockedFiles = computed(
        () =>
            this.files().some((f) => this.isBlocked(f) || this.isZeroSize(f)) ||
            [...this.fileServerErrors().values()].some((error) => !error.canRetry)
    );
    readonly isValid = computed(
        () => !this.hasBlockedFiles() && (this.files().length > 0 || this.folderName().trim().length > 0)
    );
    readonly totalSizeBytes = computed(() => this.files().reduce((sum, f) => sum + f.size, 0));
    /** Upload limits from the backend; null until loaded or when unknown. */
    private readonly uploadLimits = toSignal(
        this.storageApiService.getUploadLimits().pipe(
            map(usableUploadLimits),
            catchError(() => of(null))
        ),
        { initialValue: null }
    );
    /** Size-cap hint for the file list; null when the limits are unknown. */
    protected readonly uploadLimitsHint = computed(() => describeUploadLimits(this.uploadLimits()));
    protected readonly uploadLimitsHintId = 'create-folder-dialog-upload-limits';

    ngOnInit(): void {
        if (this.data.folderPath) {
            this.selectedPath.set(this.data.folderPath);
        }
        this.loadFolderTree();
        this.closeThroughCancelOnDismiss();
    }

    @HostListener('document:click')
    onDocumentClick(): void {
        this.dropdownOpen.set(false);
    }

    toggleDropdown(event: MouseEvent): void {
        event.stopPropagation();
        this.dropdownOpen.update((v) => !v);
    }

    stopPropagation(event: MouseEvent): void {
        event.stopPropagation();
    }

    selectFolder(path: string): void {
        this.selectedPath.set(path);
        this.dropdownOpen.set(false);
    }

    isSelected(path: string): boolean {
        return this.selectedPath() === path;
    }

    toggleExpand(event: Event, node: StorageFolderNode): void {
        event.stopPropagation();
        node.isExpanded = !node.isExpanded;
        this.rootNodes.update((n) => [...n]);
    }

    onFilesUploaded(files: FileList): void {
        if (files.length) {
            this.tryAddFiles(Array.from(files));
        }
    }

    onFileInputChange(event: Event): void {
        const input = event.target as HTMLInputElement;
        if (input.files?.length) {
            this.tryAddFiles(Array.from(input.files));
        }
        input.value = '';
    }

    removeFile(index: number): void {
        const removed = this.files()[index];
        this.files.update((list) => list.filter((_, i) => i !== index));
        if (removed && this.fileServerErrors().has(removed.name)) {
            this.fileServerErrors.update((m) => {
                const next = new Map(m);
                next.delete(removed.name);
                return next;
            });
        }
    }

    isArchive(file: File): boolean {
        // No limits, no badge: only the backend's rule decides what gets unpacked.
        const limits = this.uploadLimits();
        return limits !== null && isArchiveForLimits(file.name, limits);
    }

    isBlocked(file: File): boolean {
        const ext = file.name.toLowerCase().split('.').pop() ?? '';
        return CreateFolderDialogComponent.BLOCKED_EXTENSIONS.has(ext);
    }

    isZeroSize(file: File): boolean {
        return file.size === 0;
    }

    getFileError(file: File): UploadErrorDescription | null {
        return this.fileServerErrors().get(file.name) ?? null;
    }

    onConfirm(): void {
        if (!this.isValid() || this.isUploading() || this.confirmInFlight()) return;
        const destination = this.selectedPath();
        const subfolder = this.folderName().trim();
        const targetPath = subfolder ? (destination ? `${destination}/${subfolder}` : subfolder) : destination;
        const files = this.files();
        if (!files.length && this.uploadedFiles.size > 0) {
            // Everything left over after a partial upload was removed: nothing more to send.
            this.closeWithUploads();
            return;
        }
        const mkdirOnly = files.length === 0;

        this.fileServerErrors.set(new Map());
        this.confirmInFlight.set(true);

        const uploadPlan$: Observable<File[] | null> = mkdirOnly
            ? of([])
            : this.storageUploadService.confirmUploadPlan(targetPath, files);

        uploadPlan$
            .pipe(
                switchMap((filesToUpload) => {
                    if (!filesToUpload) return EMPTY;
                    this.isUploading.set(true);
                    return mkdirOnly ? this.createFolder(targetPath) : this.uploadFiles(targetPath, filesToUpload);
                }),
                takeUntilDestroyed(this.destroyRef)
            )
            .subscribe({
                next: (res) => {
                    if (res.type === 'mkdir') {
                        this.dialogRef.close(res);
                        return;
                    }
                    this.applyUploadBatch(res.batch);
                },
                // Upload failures come back in the batch; only mkdir or the overwrite check error.
                error: (error: unknown) => {
                    this.confirmInFlight.set(false);
                    this.isUploading.set(false);
                    const fallback = mkdirOnly ? 'Failed to create folder' : 'Failed to check existing files';
                    this.toastService.error(
                        error instanceof HttpErrorResponse ? extractHttpErrorMessage(error, fallback) : fallback
                    );
                },
                complete: () => {
                    this.confirmInFlight.set(false);
                    this.isUploading.set(false);
                },
            });
    }

    /** Closes the dialog (Cancel, Escape, backdrop), asking first while files are uploading. */
    onCancel(): void {
        if (this.isConfirmingClose) return;
        if (!this.isUploading()) {
            this.closeKeepingUploads();
            return;
        }
        this.isConfirmingClose = true;
        this.confirmationDialogService
            .confirm(CLOSE_DURING_UPLOAD_CONFIRMATION)
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe((result) => {
                this.isConfirmingClose = false;
                // Always an 'upload' result: a file cancelled mid-send may still have landed.
                if (result === true || this.closeDeferredByConfirmation) this.closeWithUploads();
            });
    }

    private closeKeepingUploads(): void {
        if (this.uploadedFiles.size > 0) {
            this.closeWithUploads();
            return;
        }
        this.dialogRef.close();
    }

    private createFolder(path: string): Observable<{ type: 'mkdir'; path: string }> {
        if (!path) return EMPTY;
        return this.storageApiService.mkdir(path).pipe(map(() => ({ type: 'mkdir' as const, path })));
    }

    private uploadFiles(
        targetPath: string,
        files: File[]
    ): Observable<{ type: 'upload'; batch: StorageUploadBatchResult }> {
        // The stream endpoint creates missing folders on the way, so no mkdir first.
        return this.storageUploadService.uploadEach(targetPath, files).pipe(
            tap((outcome) => {
                if (outcome.ok) this.uploadedFiles.add(outcome.file);
            }),
            toArray(),
            map((outcomes) => ({ type: 'upload' as const, batch: toUploadBatchResult(outcomes) }))
        );
    }

    private loadFolderTree(): void {
        this.storageApiService
            .tree()
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe({
                next: (response) => {
                    const roots = toFolderNodes(response.tree.children);
                    this.rootNodes.set(roots);
                    this.allNodes.set(flattenFolderNodes(roots));
                    this.isLoadingRoot.set(false);
                },
                error: () => this.isLoadingRoot.set(false),
            });
    }

    private buildVisible(nodes: StorageFolderNode[]): StorageFolderNode[] {
        const result: StorageFolderNode[] = [];
        for (const node of nodes) {
            result.push(node);
            if (node.isExpanded && node.children.length > 0) {
                result.push(...this.buildVisible(node.children));
            }
        }
        return result;
    }

    private addFiles(newFiles: File[]): void {
        this.files.update((existing) => {
            const names = new Set(existing.map((f) => f.name));
            return [...existing, ...newFiles.filter((f) => !names.has(f.name))];
        });
    }

    private applyUploadBatch(batch: StorageUploadBatchResult): void {
        if (!batch.failed.length) {
            if (this.isConfirmingClose) {
                this.closeDeferredByConfirmation = true;
                return;
            }
            this.closeWithUploads();
            return;
        }
        // Keep only what failed, so the next Confirm sends just those files again. Files skipped for
        // lack of Files/Update were never sent and are dropped too (the user agreed). Nothing can be
        // added between Confirm and here (isAddingFilesBlocked), so the list holds only this attempt.
        const failedFiles = new Set(batch.failed.map((failure) => failure.file));
        this.files.update((list) => list.filter((file) => failedFiles.has(file)));
        this.fileServerErrors.set(
            new Map(batch.failed.map((failure) => [failure.file.name, describeUploadError(failure.error)]))
        );
        this.toastService.error(describeUploadFailures(batch.failed));
    }

    /** Adds the files unless an attempt is running; refusing them is announced, never silent. */
    private tryAddFiles(newFiles: File[]): void {
        if (this.isAddingFilesBlocked()) {
            this.toastService.info('Wait for the current upload to finish before adding more files.');
            return;
        }
        this.addFiles(newFiles);
    }

    private closeWithUploads(): void {
        this.dialogRef.close({ type: 'upload', count: this.uploadedFiles.size });
    }

    /** Routes backdrop click and Escape through onCancel, so an upload is never dropped unasked. */
    private closeThroughCancelOnDismiss(): void {
        this.dialogRef.disableClose = true;
        merge(
            this.dialogRef.backdropClick,
            this.dialogRef.keydownEvents.pipe(
                filter((event) => event.key === 'Escape' && !hasModifierKey(event)),
                tap((event) => event.preventDefault())
            )
        )
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe(() => this.onCancel());
    }
}
