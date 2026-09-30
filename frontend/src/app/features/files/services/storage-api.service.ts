import { HttpClient, HttpHeaders } from '@angular/common/http';
import { inject, Injectable, signal } from '@angular/core';
import { ActionCode, ResourceCode } from '@shared/models';
import { Observable, of, retry, throwError, timer } from 'rxjs';
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
import { normalizeStoragePath } from '../utils/storage-path.utils';
import { UPLOAD_MAX_ATTEMPTS, uploadRetryDelayMs } from '../utils/upload-retry.utils';

@Injectable({
    providedIn: 'root',
})
export class StorageApiService {
    private http = inject(HttpClient);
    private configService = inject(ConfigService);

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

    /** Fetches the upload size caps and free space; emits null without Files/Read. */
    getUploadLimits(): Observable<StorageUploadLimits | null> {
        return this.http.get<StorageUploadLimits | null>(`${this.apiUrl}upload-limits/`, {
            context: withPermission<StorageUploadLimits | null>(ResourceCode.Files, ActionCode.Read, null),
        });
    }

    /** Streams one file to storage; retries 429/503 after Retry-After, up to UPLOAD_MAX_ATTEMPTS. */
    uploadStream(path: string, file: File): Observable<StorageStreamUploadResponse> {
        const normalized = normalizeStoragePath(path);
        // Built by hand because HttpParams leaves "+" unescaped and Django reads it as a space.
        const query =
            `?filename=${encodeURIComponent(file.name)}` +
            (normalized ? `&path=${encodeURIComponent(normalized)}` : '');

        // The File itself is the body; FormData or reading it into memory would defeat streaming.
        return this.http
            .post<StorageStreamUploadResponse>(`${this.apiUrl}upload/stream${query}`, file, {
                headers: new HttpHeaders({ 'Content-Type': 'application/octet-stream' }),
            })
            .pipe(
                retry({
                    count: UPLOAD_MAX_ATTEMPTS - 1,
                    delay: (error: unknown) => {
                        const delayMs = uploadRetryDelayMs(error);
                        return delayMs === null ? throwError(() => error) : timer(delayMs);
                    },
                })
            );
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

    private normalizeCopyTargetPath(path: string): string {
        const normalized = normalizeStoragePath(path);
        return normalized === '' ? '/' : normalized;
    }
}
