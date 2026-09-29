import { inject, Injectable } from '@angular/core';
import { formatFileSize } from '@shared/utils';
import { catchError, concat, defer, EMPTY, from, Observable, of, switchMap } from 'rxjs';
import { map, mergeMap, toArray } from 'rxjs/operators';

import { ToastService } from '../../../services/notifications';
import {
    StorageStreamUploadResponse,
    StorageUploadBatchResult,
    StorageUploadOutcome,
    StorageUploadResult,
} from '../models/storage.models';
import { FileTooLargeError, isStorageQuotaExceeded, UploadSkippedError } from '../utils/upload-error.utils';
import { uploadLimitFor, usableUploadLimits } from '../utils/upload-limits.utils';
import { StorageApiService } from './storage-api.service';

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

/** Multi-file uploads: size pre-flight, free-space warning and bounded concurrency.
 *  Root-provided: select-storage-files-dialog is opened from the flow editor, outside the files feature. */
@Injectable({
    providedIn: 'root',
})
export class StorageUploadService {
    private readonly storageApiService = inject(StorageApiService);
    private readonly toastService = inject(ToastService);

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
}
