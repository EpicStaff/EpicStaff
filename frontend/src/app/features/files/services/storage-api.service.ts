import { HttpClient } from '@angular/common/http';
import { inject, Injectable, signal } from '@angular/core';
import { EMPTY, Observable, of } from 'rxjs';
import { map } from 'rxjs/operators';

import { ConfigService } from '../../../services/config/config.service';
import { AddFilesPayload } from '../components/create-folder-dialog/create-folder-dialog.component';
import {
    GraphFileRecord,
    SessionOutputFile,
    StorageItem,
    StorageItemInfo,
    StorageUploadResponse,
} from '../models/storage.models';

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
            })
            .pipe(map((res) => res.items ?? []));
    }

    handleAddFilesResult(
        result: AddFilesPayload,
        filterFiles: (files: File[]) => File[] = (f) => f
    ): Observable<{ type: 'mkdir'; path: string } | { type: 'upload'; count: number }> {
        const targetPath = result.targetPath;

        if (result.mkdirOnly) {
            if (!targetPath) return EMPTY;
            return this.mkdir(targetPath).pipe(map(() => ({ type: 'mkdir' as const, path: targetPath })));
        }

        const validFiles = filterFiles(result.files);
        if (!validFiles.length) return EMPTY;

        const upload$ = targetPath
            ? this.ensureFolderAndUpload(targetPath, validFiles).pipe(map((r) => r.uploadedCount))
            : this.uploadMany('', validFiles).pipe(map(() => validFiles.length));

        return upload$.pipe(map((count) => ({ type: 'upload' as const, count })));
    }

    ensureFolderAndUpload(targetFolder: string, files: File[]): Observable<{ uploadedCount: number }> {
        const normalizedTarget = this.normalizePath(targetFolder);
        if (!files.length) {
            return of({ uploadedCount: 0 });
        }
        return this.uploadMany(normalizedTarget, files).pipe(map(() => ({ uploadedCount: files.length })));
    }

    info(path: string): Observable<StorageItemInfo> {
        return this.http.get<StorageItemInfo>(`${this.apiUrl}info/`, {
            params: { path },
        });
    }

    download(path: string): void {
        const url = `${this.apiUrl}download/?path=${encodeURIComponent(path)}`;
        window.open(url, '_blank');
    }

    getDownloadUrl(path: string): string {
        return `${this.apiUrl}download/?path=${encodeURIComponent(path)}`;
    }

    downloadBlob(path: string): Observable<Blob> {
        return this.http.get(`${this.apiUrl}download/`, {
            params: { path },
            responseType: 'blob',
        });
    }

    upload(path: string, file: File): Observable<StorageUploadResponse> {
        return this.uploadMany(path, [file]);
    }

    uploadMany(path: string, files: File[]): Observable<StorageUploadResponse> {
        const formData = new FormData();
        files.forEach((file) => formData.append('files', file));
        formData.append('path', this.normalizePath(path) || '/');

        return this.http.post<StorageUploadResponse>(`${this.apiUrl}upload/`, formData);
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
