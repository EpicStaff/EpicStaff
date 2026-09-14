import { HttpClient, HttpErrorResponse } from '@angular/common/http';
import { inject, Injectable, signal } from '@angular/core';
import { ActionCode, ResourceCode } from '@shared/models';
import { catchError, EMPTY, Observable, of, switchMap, throwError } from 'rxjs';
import { map } from 'rxjs/operators';

import { withPermission } from '../../../core/http/permission-context';
import { ConfigService } from '../../../services/config/config.service';
import { ConfirmationDialogData, ConfirmationDialogService } from '../../../shared/components/cofirm-dialog';
import { AddFilesPayload } from '../components/create-folder-dialog/create-folder-dialog.component';
import {
    GraphFileRecord,
    SessionOutputFile,
    StorageFileRecord,
    StorageItem,
    StorageItemInfo,
    StorageTreeResponse,
    StorageUploadResponse,
} from '../models/storage.models';
import { isArchiveFileName } from '../utils/storage-file.utils';

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

    ensureFolderAndUpload(targetFolder: string, files: File[]): Observable<{ uploadedCount: number }> {
        const normalizedTarget = this.normalizePath(targetFolder);
        if (!files.length) {
            return of({ uploadedCount: 0 });
        }
        return this.uploadMany(normalizedTarget, files).pipe(map(() => ({ uploadedCount: files.length })));
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
        });
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
