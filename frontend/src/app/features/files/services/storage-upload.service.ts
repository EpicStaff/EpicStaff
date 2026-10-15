import { HttpErrorResponse } from '@angular/common/http';
import { inject, Injectable } from '@angular/core';
import { ConfirmationDialogData, ConfirmationDialogService } from '@shared/components';
import { ActionCode, ResourceCode } from '@shared/models';
import { escapeHtml, formatFileSize } from '@shared/utils';
import { catchError, concat, defer, EMPTY, from, Observable, of, switchMap, throwError } from 'rxjs';
import { map, mergeMap, toArray } from 'rxjs/operators';

import { PermissionsService } from '../../../services/auth/permissions.service';
import { ToastService } from '../../../services/notifications';
import {
    StorageItem,
    StorageStreamUploadResponse,
    StorageUploadBatchResult,
    StorageUploadOutcome,
    StorageUploadResult,
} from '../models/storage.models';
import { normalizeStoragePath } from '../utils/storage-path.utils';
import { FileTooLargeError, isStorageQuotaExceeded, UploadSkippedError } from '../utils/upload-error.utils';
import { uploadLimitFor, usableUploadLimits } from '../utils/upload-limits.utils';
import { StorageApiService } from './storage-api.service';

interface OverwritePreview {
    fileConflicts: string[];
    folderConflicts: string[];
}

/** What the overwrite dialog has to explain: the conflicts and whether files may be replaced. */
interface OverwriteDialogContext {
    preview: OverwritePreview;
    targetPath: string;
    /** False without Files/Update: the server refuses to overwrite, so file conflicts are skipped. */
    canReplaceFiles: boolean;
    /** False when every file is a skipped conflict: the dialog only informs, there is nothing to send. */
    hasFilesToUpload: boolean;
}

/** Parallel uploads; above the backend's per-organization limit (3) the extras get 429s. */
export const UPLOAD_CONCURRENCY = 3;

/** Collects a batch's outcomes into the two lists callers report from. */
export function toUploadBatchResult(outcomes: StorageUploadOutcome[]): StorageUploadBatchResult {
    return {
        uploaded: outcomes.flatMap((outcome) => (outcome.ok ? [{ file: outcome.file, result: outcome.result }] : [])),
        failed: outcomes.flatMap((outcome) => (outcome.ok ? [] : [{ file: outcome.file, error: outcome.error }])),
    };
}

/** Maps a streaming-upload response to a StorageUploadResult. */
function toUploadResult(response: StorageStreamUploadResponse): StorageUploadResult {
    return response.extracted
        ? { type: 'archive', extracted: response.extracted }
        : { type: 'file', path: response.path, size: response.size ?? 0 };
}

/** Multi-file uploads: overwrite check, size pre-flight, free-space warning and bounded concurrency.
 *  Root-provided: select-storage-files-dialog is opened from the flow editor, outside the files feature. */
@Injectable({
    providedIn: 'root',
})
export class StorageUploadService {
    private readonly storageApiService = inject(StorageApiService);
    private readonly toastService = inject(ToastService);
    private readonly confirmationDialogService = inject(ConfirmationDialogService);
    private readonly permissionsService = inject(PermissionsService);

    /**
     * Asks about names that already exist in `targetPath` and resolves to the files to send, or
     * null when the upload is cancelled or nothing is left to send. Without Files/Update, files
     * that would replace an existing file are left out (the server would refuse them); the dialog
     * lists them as skipped.
     * Only `targetPath` itself is checked; the server stays the source of truth.
     */
    confirmUploadPlan(targetPath: string, files: File[]): Observable<File[] | null> {
        return this.findOverwritePreview(targetPath, files).pipe(
            switchMap((preview) => {
                if (!this.hasOverwriteRisk(preview)) return of(files);
                const canReplaceFiles = this.permissionsService.can(ResourceCode.Files, ActionCode.Update);
                const skippedNames = new Set(canReplaceFiles ? [] : preview.fileConflicts);
                const filesToUpload = files.filter((file) => !skippedNames.has(file.name));
                const hasFilesToUpload = filesToUpload.length > 0;
                const listed = preview.fileConflicts.length + preview.folderConflicts.length;
                return this.confirmationDialogService
                    .confirm(
                        this.buildOverwriteDialogData({ preview, targetPath, canReplaceFiles, hasFilesToUpload }),
                        {
                            width: listed > 3 ? '480px' : '400px',
                        }
                    )
                    .pipe(map((result) => (result === true && hasFilesToUpload ? filesToUpload : null)));
            })
        );
    }

    /** Uploads files a few at a time and emits each file's outcome as it settles; never errors.
     *  Files over their size cap fail without being sent; after a quota error, unstarted files are skipped. */
    uploadEach(path: string, files: File[]): Observable<StorageUploadOutcome> {
        if (!files.length) return EMPTY;

        return this.storageApiService.getUploadLimits().pipe(
            catchError(() => of(null)),
            switchMap((response) => {
                const limits = usableUploadLimits(response);
                const tooLarge: StorageUploadOutcome[] = [];
                const toSend: File[] = [];
                for (const file of files) {
                    const limit = limits ? uploadLimitFor(file.name, limits) : null;
                    if (limit !== null && file.size > limit) {
                        tooLarge.push({ ok: false, file, error: new FileTooLargeError(limit) });
                    } else {
                        toSend.push(file);
                    }
                }
                if (limits) this.warnIfMayNotFit(toSend, limits.free_bytes);
                return concat(from(tooLarge), this.sendEach(path, toSend));
            })
        );
    }

    /** Like uploadEach, but emits one batch result once every file has settled. */
    uploadMany(path: string, files: File[]): Observable<StorageUploadBatchResult> {
        return this.uploadEach(path, files).pipe(toArray(), map(toUploadBatchResult));
    }

    /** Warns when the files may not fit in free space; only a warning, the backend decides. */
    private warnIfMayNotFit(files: File[], freeBytes: number): void {
        if (!files.length || !Number.isFinite(freeBytes)) return;
        const totalBytes = files.reduce((sum, file) => sum + file.size, 0);
        if (totalBytes <= freeBytes) return;
        this.toastService.warning(
            `These files may not fit in the remaining storage (${formatFileSize(Math.max(0, freeBytes), 'auto')} free); ` +
                'overwritten files free up their space.'
        );
    }

    private sendEach(path: string, files: File[]): Observable<StorageUploadOutcome> {
        if (!files.length) return EMPTY;

        return defer(() => {
            let quotaError: unknown = null;
            return from(files).pipe(
                mergeMap(
                    (file) =>
                        // defer reads quotaError when a slot frees up, not when the file was queued.
                        defer((): Observable<StorageUploadOutcome> => {
                            if (quotaError) return of({ ok: false, file, error: new UploadSkippedError(quotaError) });
                            return this.storageApiService.uploadStream(path, file).pipe(
                                map(
                                    (response): StorageUploadOutcome => ({
                                        ok: true,
                                        file,
                                        result: toUploadResult(response),
                                    })
                                ),
                                catchError((error: unknown) => {
                                    if (isStorageQuotaExceeded(error)) quotaError ??= error;
                                    return of<StorageUploadOutcome>({ ok: false, file, error });
                                })
                            );
                        }),
                    UPLOAD_CONCURRENCY
                )
            );
        });
    }

    private hasOverwriteRisk(preview: OverwritePreview): boolean {
        return preview.fileConflicts.length > 0 || preview.folderConflicts.length > 0;
    }

    private findOverwritePreview(targetPath: string, files: File[]): Observable<OverwritePreview> {
        return this.storageApiService.list(normalizeStoragePath(targetPath)).pipe(
            map((items) => this.buildOverwritePreview(items, files)),
            catchError((error: unknown) => {
                if (error instanceof HttpErrorResponse && error.status === 404) {
                    return of(this.buildOverwritePreview([], files));
                }
                return throwError(() => error);
            })
        );
    }

    private buildOverwritePreview(items: StorageItem[], files: File[]): OverwritePreview {
        const existingFiles = new Set(items.filter((item) => item.type === 'file').map((item) => item.name));
        const existingFolders = new Set(items.filter((item) => item.type === 'folder').map((item) => item.name));
        const uploadedNames = [...new Set(files.map((file) => file.name))];
        return {
            fileConflicts: uploadedNames.filter((name) => existingFiles.has(name)),
            folderConflicts: uploadedNames.filter((name) => existingFolders.has(name)),
        };
    }

    private buildOverwriteDialogData(context: OverwriteDialogContext): ConfirmationDialogData {
        const { preview, targetPath, canReplaceFiles, hasFilesToUpload } = context;
        const normalized = normalizeStoragePath(targetPath);
        const folderLabel = escapeHtml(normalized ? `/${normalized}` : '/');
        const fileCount = preview.fileConflicts.length;
        const folderCount = preview.folderConflicts.length;
        const listedNames = [...preview.fileConflicts, ...preview.folderConflicts];
        const onlyFolders = folderCount > 0 && fileCount === 0;
        // Mark skipped files only when folder names share the list; otherwise every entry is skipped.
        const markedAsSkipped = new Set(!canReplaceFiles && folderCount ? preview.fileConflicts : []);

        const parts: string[] = [];
        if (fileCount && folderCount) {
            parts.push(`${folderLabel} already contains files and folders with these names.`);
        } else if (fileCount) {
            parts.push(
                `${folderLabel} already contains ${fileCount > 1 ? 'files' : 'a file'} with ${
                    fileCount > 1 ? 'these names' : 'this name'
                }.`
            );
        } else {
            parts.push(
                `${folderLabel} already contains ${folderCount > 1 ? 'folders' : 'a folder'} with ${
                    folderCount > 1 ? 'these names' : 'this name'
                }.`
            );
        }

        if (fileCount && canReplaceFiles) {
            parts.push(`Uploading will replace the existing ${fileCount > 1 ? 'files' : 'file'}.`);
        }
        if (fileCount && !canReplaceFiles) {
            parts.push(
                `You don't have permission to replace existing files, so ${
                    fileCount > 1 ? 'these files' : 'this file'
                } will be skipped.`
            );
        }
        if (folderCount) {
            parts.push('A folder with the same name will not be replaced.');
        }
        parts.push(hasFilesToUpload ? 'Cancel will skip the entire upload.' : 'There is nothing left to upload.');

        let title = 'Items already exist';
        if (onlyFolders) {
            title = folderCount > 1 ? 'Folders already exist' : 'Folder already exists';
        } else if (fileCount && !folderCount) {
            title = fileCount > 1 ? 'Files already exist' : 'File already exists';
        }

        let confirmText = 'Replace';
        if (onlyFolders) {
            confirmText = 'Upload anyway';
        } else if (!canReplaceFiles) {
            confirmText = 'Skip and upload';
        }

        return {
            title,
            message: parts.join('<br>'),
            confirmText,
            cancelText: hasFilesToUpload ? 'Cancel' : 'Close',
            hideConfirm: !hasFilesToUpload,
            type: 'warning',
            cautionTitle: 'Existing names',
            caution: this.buildConflictListHtml(listedNames, markedAsSkipped),
        };
    }

    private buildConflictListHtml(names: string[], markedAsSkipped: ReadonlySet<string>): string {
        const visible = names.slice(0, 12);
        const extra = names.length - visible.length;
        const lines = visible.map((name) => `• ${escapeHtml(name)}${markedAsSkipped.has(name) ? ' (skipped)' : ''}`);
        if (extra > 0) {
            lines.push(`and ${extra} more`);
        }
        return lines.join('<br>');
    }
}
