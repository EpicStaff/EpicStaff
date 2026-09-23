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

/** Kept at or below the backend's per-organization upload limit (4 by default), or
 *  the extra requests only come back as 429s. */
export const UPLOAD_CONCURRENCY = 3;

/** Collects a batch's outcomes into the two lists callers report from. */
export function toUploadBatchResult(outcomes: StorageUploadOutcome[]): StorageUploadBatchResult {
    return {
        uploaded: outcomes.flatMap((outcome) => (outcome.ok ? [{ file: outcome.file, result: outcome.result }] : [])),
        failed: outcomes.flatMap((outcome) => (outcome.ok ? [] : [{ file: outcome.file, error: outcome.error }])),
    };
}

/** Maps one streaming-upload answer to the result shape callers already use. */
function toUploadResult(response: StorageStreamUploadResponse): StorageUploadResult {
    return response.extracted
        ? { type: 'archive', extracted: response.extracted }
        : { type: 'file', path: response.path, size: response.size ?? 0 };
}

/**
 * Multi-file uploads: the size pre-flight, the free-space warning and the
 * concurrency around StorageApiService.uploadStream. Root-provided because it is
 * stateless and one of its callers (select-storage-files-dialog) is opened from
 * the flow editor, outside any files-feature injector.
 */
@Injectable({
    providedIn: 'root',
})
export class StorageUploadService {
    private readonly storageApiService = inject(StorageApiService);
    private readonly toastService = inject(ToastService);

    /**
     * Emits each file's outcome as soon as it settles and completes after the last
     * one; never errors, so a partial success is never hidden behind the first failure.
     *
     * The limits are read fresh for every batch (free space changes with each upload),
     * so a file over its size cap is reported without sending it: the browser would
     * only see the 413 after streaming the whole body. If they can't be read, every
     * file is sent and the backend decides.
     *
     * One request per file, a few in flight at a time, so the bounded-memory proxy
     * on the backend doesn't queue. A file waiting to retry keeps its slot. A rejected
     * file doesn't cancel its siblings; once one exceeds the storage quota, files not
     * yet started aren't sent. Unsubscribing cancels whatever is still running.
     */
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

    /** uploadEach, reported once the whole batch has settled. */
    uploadMany(path: string, files: File[]): Observable<StorageUploadBatchResult> {
        return this.uploadEach(path, files).pipe(toArray(), map(toUploadBatchResult));
    }

    /** Only a warning: free space is a snapshot that doesn't credit the files an upload
     *  overwrites, so the backend has the final word. */
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
                        // mergeMap starts a queued file only when a slot frees up, and
                        // defer reads quotaError at that moment, not when it was queued.
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
