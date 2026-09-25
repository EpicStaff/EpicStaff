import { HttpClient, HttpErrorResponse, HttpHeaders } from '@angular/common/http';
import { inject, Injectable, signal } from '@angular/core';
import { ConfirmationDialogData, ConfirmationDialogService } from '@shared/components';
import { ActionCode, ResourceCode } from '@shared/models';
import { catchError, Observable, of, retry, switchMap, throwError, timer } from 'rxjs';
import { map } from 'rxjs/operators';

import { withPermission } from '../../../core/http/permission-context';
import { ConfigService } from '../../../services/config';
import {
    GraphFileRecord,
    SessionOutputFile,
    StorageFileRecord,
    StorageItem,
    StorageItemInfo,
    StorageStreamUploadResponse,
    StorageTreeResponse,
    StorageUploadLimits,
} from '../models/storage.models';
import { isArchiveFileName } from '../utils/storage-file.utils';
import { getUploadErrorCode, UploadErrorCode } from '../utils/upload-error.utils';

/** Attempts per file, the first one included, while the server answers 429/503. */
export const UPLOAD_MAX_ATTEMPTS = 5;
/** Waits used when a 429/503 carries no readable Retry-After. */
export const UPLOAD_RETRY_FALLBACK_SECONDS = 30;
export const STORAGE_UNAVAILABLE_RETRY_FALLBACK_SECONDS = 5;
/** Upper bound on one wait, whatever Retry-After says. */
const UPLOAD_RETRY_MAX_SECONDS = 120;

/** 429 (org upload limit) and 503 (slots busy, storage unavailable) are the only
 *  answers where sending the same file again later can succeed. */
const RETRYABLE_UPLOAD_STATUSES = new Set([429, 503]);

/** How long to wait before re-sending after `error`, or null when it must not be retried. */
function uploadRetryDelayMs(error: unknown): number | null {
    if (!(error instanceof HttpErrorResponse) || !RETRYABLE_UPLOAD_STATUSES.has(error.status)) return null;
    const fallback =
        getUploadErrorCode(error) === UploadErrorCode.StorageUnavailable
            ? STORAGE_UNAVAILABLE_RETRY_FALLBACK_SECONDS
            : UPLOAD_RETRY_FALLBACK_SECONDS;
    const seconds = parseRetryAfterSeconds(error.headers.get('Retry-After')) ?? fallback;
    return Math.min(seconds, UPLOAD_RETRY_MAX_SECONDS) * 1000;
}

/** Retry-After is either delay-seconds or an HTTP date (RFC 9110 §10.2.3). */
function parseRetryAfterSeconds(header: string | null): number | null {
    if (!header) return null;
    const value = header.trim();
    if (/^\d+$/.test(value)) return Number(value);
    const date = Date.parse(value);
    if (Number.isNaN(date)) return null;
    return Math.max(0, Math.ceil((date - Date.now()) / 1000));
}

interface OverwritePreview {
    fileConflicts: string[];
    folderConflicts: string[];
    archiveRisk: boolean;
}

@Injectable({
    providedIn: 'root',
})
export class StorageApiService {
    private http = inject(HttpClient);
    private configService = inject(ConfigService);
    private confirmationDialogService = inject(ConfirmationDialogService);

    readonly refreshTick = signal(0);

    triggerRefresh(): void {
        this.refreshTick.update((n) => n + 1);
    }

    private get apiUrl(): string {
        return `${this.configService.apiUrl}storage/`;
    }

    list(path: string): Observable<StorageItem[]> {
        return this.http
            .get<{ path: string; items: StorageItem[] }>(`${this.apiUrl}list/`, {
                params: { path },
                context: withPermission<{ path: string; items: StorageItem[] }>(ResourceCode.Files, ActionCode.Read, {
                    path,
                    items: [],
                }),
            })
            .pipe(map((res) => res.items ?? []));
    }

    confirmOverwrite(targetPath: string, files: File[]): Observable<boolean> {
        return this.findOverwritePreview(targetPath, files).pipe(
            switchMap((preview) => {
                if (!this.hasOverwriteRisk(preview)) return of(true);
                const listed = preview.fileConflicts.length + preview.folderConflicts.length;
                return this.confirmationDialogService
                    .confirm(this.buildOverwriteDialogData(preview, targetPath), {
                        width: listed > 3 ? '480px' : '400px',
                    })
                    .pipe(map((result) => result === true));
            })
        );
    }

    private hasOverwriteRisk(preview: OverwritePreview): boolean {
        return preview.fileConflicts.length > 0 || preview.folderConflicts.length > 0 || preview.archiveRisk;
    }

    private findOverwritePreview(targetPath: string, files: File[]): Observable<OverwritePreview> {
        return this.list(this.normalizePath(targetPath)).pipe(
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
            archiveRisk: files.some((file) => isArchiveFileName(file.name)) && items.length > 0,
        };
    }

    private buildOverwriteDialogData(preview: OverwritePreview, targetPath: string): ConfirmationDialogData {
        const normalized = this.normalizePath(targetPath);
        const folderLabel = this.escapeHtml(normalized ? `/${normalized}` : '/');
        const fileCount = preview.fileConflicts.length;
        const folderCount = preview.folderConflicts.length;
        const listedNames = [...preview.fileConflicts, ...preview.folderConflicts];
        const onlyFolders = folderCount > 0 && fileCount === 0 && !preview.archiveRisk;

        const parts: string[] = [];
        if (fileCount && folderCount) {
            parts.push(`${folderLabel} already contains files and folders with these names.`);
        } else if (fileCount) {
            parts.push(
                `${folderLabel} already contains ${fileCount > 1 ? 'files' : 'a file'} with ${
                    fileCount > 1 ? 'these names' : 'this name'
                }.`
            );
        } else if (folderCount) {
            parts.push(
                `${folderLabel} already contains ${folderCount > 1 ? 'folders' : 'a folder'} with ${
                    folderCount > 1 ? 'these names' : 'this name'
                }.`
            );
        } else {
            parts.push(`${folderLabel} already has items.`);
        }

        if (fileCount) {
            parts.push(`Uploading will replace the existing ${fileCount > 1 ? 'files' : 'file'}.`);
        }
        if (folderCount) {
            parts.push('A folder with the same name will not be replaced.');
        }
        if (preview.archiveRisk) {
            parts.push('Archives are extracted on the server and may replace existing files with matching names.');
        }
        parts.push('Cancel will skip the entire upload.');

        let title = 'Items already exist';
        if (preview.archiveRisk && !fileCount && !folderCount) {
            title = 'Archive may replace files';
        } else if (onlyFolders) {
            title = folderCount > 1 ? 'Folders already exist' : 'Folder already exists';
        } else if (fileCount && !folderCount) {
            title = fileCount > 1 ? 'Files already exist' : 'File already exists';
        }

        return {
            title,
            message: parts.join('<br>'),
            confirmText: onlyFolders ? 'Upload anyway' : 'Replace',
            cancelText: 'Cancel',
            type: 'warning',
            cautionTitle: listedNames.length ? 'Existing names' : undefined,
            caution: listedNames.length ? this.buildConflictListHtml(listedNames) : undefined,
        };
    }

    private buildConflictListHtml(names: string[]): string {
        const visible = names.slice(0, 12);
        const extra = names.length - visible.length;
        const lines = visible.map((name) => `• ${this.escapeHtml(name)}`);
        if (extra > 0) {
            lines.push(`and ${extra} more`);
        }
        return lines.join('<br>');
    }

    private escapeHtml(value: string): string {
        return value
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#39;');
    }

    tree(path = ''): Observable<StorageTreeResponse> {
        return this.http.get<StorageTreeResponse>(`${this.apiUrl}tree/`, {
            params: { path },
        });
    }

    filesByIds(ids: number[]): Observable<StorageFileRecord[]> {
        if (!ids.length) return of([]);
        return this.http.get<StorageFileRecord[]>(`${this.apiUrl}files/`, {
            params: { ids: ids.join(',') },
            context: withPermission<StorageFileRecord[]>(ResourceCode.Files, ActionCode.Read, []),
        });
    }

    info(path: string): Observable<StorageItemInfo> {
        return this.http.get<StorageItemInfo>(`${this.apiUrl}info/`, {
            params: { path },
        });
    }

    /** `maxBytes` asks for only the first bytes of the file (HTTP Range). */
    downloadBlob(path: string, maxBytes?: number): Observable<Blob> {
        return this.http.get(`${this.apiUrl}download/`, {
            params: { path },
            responseType: 'blob',
            headers: maxBytes !== undefined ? new HttpHeaders({ Range: `bytes=0-${maxBytes - 1}` }) : undefined,
        });
    }

    /** The backend's size caps and free space. Without Files/Read no request is made and
     *  it emits null: the limits are unknown (the backend still enforces them). */
    getUploadLimits(): Observable<StorageUploadLimits | null> {
        return this.http.get<StorageUploadLimits | null>(`${this.apiUrl}upload-limits/`, {
            context: withPermission<StorageUploadLimits | null>(ResourceCode.Files, ActionCode.Read, null),
        });
    }

    /** One file, one request; a 429/503 is re-sent after its Retry-After, up to UPLOAD_MAX_ATTEMPTS. */
    /** `uploadPath` is the endpoint path from getUploadLimits(); without it the default route is used. */
    uploadStream(path: string, file: File, uploadPath?: string): Observable<StorageStreamUploadResponse> {
        const normalized = this.normalizePath(path);
        // Built by hand because HttpParams leaves "+" unescaped and Django reads it
        // back as a space, silently renaming files like "a+b.txt".
        const query =
            `?filename=${encodeURIComponent(file.name)}` +
            (normalized ? `&path=${encodeURIComponent(normalized)}` : '');

        // The File itself is the body: the browser streams it from disk. Wrapping it
        // in FormData, or reading it into memory first, defeats the whole endpoint.
        return this.http
            .post<StorageStreamUploadResponse>(`${this.uploadStreamUrl(uploadPath)}${query}`, file, {
                headers: new HttpHeaders({ 'Content-Type': 'application/octet-stream' }),
            })
            .pipe(
                // A busy server (429/503) says when to come back; anything else is final.
                retry({
                    count: UPLOAD_MAX_ATTEMPTS - 1,
                    delay: (error: unknown) => {
                        const delayMs = uploadRetryDelayMs(error);
                        return delayMs === null ? throwError(() => error) : timer(delayMs);
                    },
                })
            );
    }

    /** The backend's upload path (DJANGO_UPLOAD_STREAM_PATH) on the API's origin, which
     *  may differ from the page's when apiUrl is absolute. */
    private uploadStreamUrl(uploadPath: string | undefined): string {
        if (!uploadPath?.startsWith('/')) return `${this.apiUrl}upload/stream`;
        const apiBase = new URL(this.configService.apiUrl, window.location.origin);
        return new URL(uploadPath, apiBase).toString();
    }

    downloadZip(paths: string[]): Observable<Blob> {
        return this.http.post(
            `${this.apiUrl}download-zip/`,
            { paths },
            {
                responseType: 'blob',
            }
        );
    }

    mkdir(path: string): Observable<void> {
        return this.http.post<void>(`${this.apiUrl}mkdir/`, { path });
    }

    delete(paths: string[]): Observable<void> {
        return this.http.delete<void>(`${this.apiUrl}delete/`, {
            body: { paths },
        });
    }

    rename(from: string, to: string): Observable<void> {
        return this.http.post<void>(`${this.apiUrl}rename/`, { from_path: from, to_path: to });
    }

    move(from: string, to: string): Observable<void> {
        return this.http.post<void>(`${this.apiUrl}move/`, {
            from_path: from,
            to_path: this.normalizeCopyTargetPath(to),
        });
    }

    copy(from: string, to: string): Observable<void> {
        return this.http.post<void>(`${this.apiUrl}copy/`, {
            from_path: from,
            to_path: this.normalizeCopyTargetPath(to),
        });
    }

    addToGraph(paths: string[], graphIds: number[]): Observable<void> {
        return this.http.post<void>(`${this.apiUrl}add-to-graph/`, {
            paths,
            graph_ids: graphIds,
        });
    }

    removeFromGraph(paths: string[], graphIds: number[]): Observable<void> {
        return this.http.delete<void>(`${this.apiUrl}remove-from-graph/`, {
            body: { paths, graph_ids: graphIds },
        });
    }

    getGraphFiles(graphId: number): Observable<GraphFileRecord[]> {
        return this.http.get<GraphFileRecord[]>(`${this.apiUrl}graph-files/`, {
            params: { graph_id: graphId.toString() },
            context: withPermission<GraphFileRecord[]>(ResourceCode.Files, ActionCode.Read, []),
        });
    }

    getSessionOutputFiles(sessionId: string): Observable<SessionOutputFile[]> {
        return this.http.get<SessionOutputFile[]>(`${this.configService.apiUrl}sessions/${sessionId}/output-files/`);
    }

    private normalizePath(path: string): string {
        return path
            .trim()
            .replace(/\\/g, '/')
            .replace(/\/{2,}/g, '/')
            .replace(/^\/+|\/+$/g, '');
    }

    private normalizeCopyTargetPath(path: string): string {
        const normalized = this.normalizePath(path);
        return normalized === '' ? '/' : normalized;
    }
}
