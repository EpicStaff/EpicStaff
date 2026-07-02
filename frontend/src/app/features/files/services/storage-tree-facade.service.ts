import { Dialog } from '@angular/cdk/dialog';
import { DestroyRef, effect, inject, Injectable, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { forkJoin, Subject } from 'rxjs';
import { finalize } from 'rxjs/operators';

import { ToastService } from '../../../services/notifications/toast.service';
import { ConfirmationDialogService } from '../../../shared/components/cofirm-dialog';
import {
    AddToFlowDialogComponent,
    AddToFlowDialogData,
    AddToFlowDialogResult,
} from '../components/add-to-flow-dialog/add-to-flow-dialog.component';
import {
    CopyToDialogComponent,
    CopyToDialogData,
    CopyToDialogResult,
} from '../components/copy-to-dialog/copy-to-dialog.component';
import {
    CreateFolderDialogComponent,
    CreateFolderDialogData,
    CreateFolderDialogResult,
} from '../components/create-folder-dialog/create-folder-dialog.component';
import { StorageDetailsDialogComponent } from '../components/storage-details-dialog/storage-details-dialog.component';
import { StorageItem, StorageItemInfo } from '../models/storage.models';
import { getFileExtension } from '../utils/storage-file.utils';
import { StorageApiService } from './storage-api.service';

export interface StorageContextActionEvent {
    action: string;
    item: StorageItem;
    selectedItems?: StorageItem[];
    renameFromPath?: string;
    targetPath?: string;
}

@Injectable()
export class StorageTreeFacade {
    private destroyRef = inject(DestroyRef);
    private storageApiService = inject(StorageApiService);
    private toastService = inject(ToastService);
    private confirmationDialogService = inject(ConfirmationDialogService);
    private dialog = inject(Dialog);

    readonly isLoading = signal<boolean>(true);
    readonly treeData = signal<StorageItem[]>([]);
    readonly selectedFile = signal<StorageItem | null>(null);
    readonly selectedItems = signal<StorageItem[]>([]);

    readonly selectInTree = new Subject<StorageItem>();

    afterTreeLoad: (() => void) | null = null;

    private watchRefreshTick = false;

    private readonly blockedUploadExtensions = new Set([
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

    constructor() {
        effect(() => {
            this.storageApiService.refreshTick();
            if (!this.watchRefreshTick) return;
            this.loadTree();
        });
    }

    init(options: { watchRefreshTick: boolean }): void {
        this.watchRefreshTick = options.watchRefreshTick;
    }

    loadTree(): void {
        this.isLoading.set(true);
        this.storageApiService
            .list('')
            .pipe(
                takeUntilDestroyed(this.destroyRef),
                finalize(() => this.isLoading.set(false))
            )
            .subscribe({
                next: (items) => {
                    this.treeData.set(this.withPaths(Array.isArray(items) ? items : [], ''));
                    this.afterTreeLoad?.();
                },
                error: () => this.toastService.error('Failed to load storage files'),
            });
    }

    reloadTreePreservingExpansion(extraPathsToExpand: string[] = []): void {
        const expandedPaths = this.collectExpandedPaths(this.treeData());
        const all = new Set<string>([...expandedPaths, ...extraPathsToExpand.filter(Boolean)]);

        this.isLoading.set(true);
        this.storageApiService
            .list('')
            .pipe(
                takeUntilDestroyed(this.destroyRef),
                finalize(() => this.isLoading.set(false))
            )
            .subscribe({
                next: (items) => {
                    this.treeData.set(this.withPaths(Array.isArray(items) ? items : [], ''));
                    if (all.size) this.restoreExpandedPaths([...all]);
                },
                error: () => this.toastService.error('Failed to load storage files'),
            });
    }

    private collectExpandedPaths(nodes: StorageItem[]): string[] {
        const paths: string[] = [];
        const walk = (list: StorageItem[]): void => {
            for (const n of list) {
                if (n.type === 'folder' && n.isExpanded && n.path) {
                    paths.push(n.path);
                    if (n.children?.length) walk(n.children);
                }
            }
        };
        walk(nodes);
        return paths;
    }

    private restoreExpandedPaths(paths: string[]): void {
        const sorted = [...paths].sort((a, b) => a.split('/').length - b.split('/').length);
        for (const path of sorted) {
            this.expandPath(path);
        }
    }

    expandPath(targetPath: string): void {
        const segments = targetPath.split('/').filter(Boolean);
        if (!segments.length) return;

        const walk = (index: number, nodes: StorageItem[], currentPath: string): void => {
            const segment = segments[index];
            const nextPath = currentPath ? `${currentPath}/${segment}` : segment;
            const match = nodes.find((n) => n.name === segment);
            if (!match || match.type !== 'folder') return;

            match.isExpanded = true;
            const isLast = index === segments.length - 1;

            if (!match.children || match.children.length === 0) {
                if (match.is_empty) {
                    this.treeData.update((data) => [...data]);
                    return;
                }
                this.storageApiService
                    .list(nextPath)
                    .pipe(takeUntilDestroyed(this.destroyRef))
                    .subscribe({
                        next: (children) => {
                            match.children = this.withPaths(Array.isArray(children) ? children : [], nextPath);
                            this.treeData.update((data) => [...data]);
                            if (!isLast) walk(index + 1, match.children ?? [], nextPath);
                        },
                    });
            } else {
                this.treeData.update((data) => [...data]);
                if (!isLast) walk(index + 1, match.children, nextPath);
            }
        };

        walk(0, this.treeData(), '');
    }

    expandAndSelectPath(targetPath: string): void {
        const segments = targetPath.split('/').filter(Boolean);
        if (segments.length === 0) return;

        const walk = (index: number, nodes: StorageItem[], currentPath: string): void => {
            const segment = segments[index];
            const nextPath = currentPath ? `${currentPath}/${segment}` : segment;
            const match = nodes.find((n) => n.name === segment);
            if (!match) return;

            const isLast = index === segments.length - 1;

            if (isLast) {
                this.selectedFile.set(match);
                setTimeout(() => this.selectInTree.next(match));
                return;
            }

            if (match.type !== 'folder') return;

            match.isExpanded = true;

            if (!match.children || match.children.length === 0) {
                this.storageApiService
                    .list(nextPath)
                    .pipe(takeUntilDestroyed(this.destroyRef))
                    .subscribe({
                        next: (children) => {
                            match.children = this.withPaths(Array.isArray(children) ? children : [], nextPath);
                            this.treeData.update((data) => [...data]);
                            walk(index + 1, match.children ?? [], nextPath);
                        },
                    });
            } else {
                this.treeData.update((data) => [...data]);
                walk(index + 1, match.children, nextPath);
            }
        };

        walk(0, this.treeData(), '');
    }

    private withPaths(items: StorageItem[], parentPath: string): StorageItem[] {
        return items.map((item) => ({
            ...item,
            path: parentPath ? `${parentPath}/${item.name}` : item.name,
        }));
    }

    onFolderToggle(item: StorageItem): void {
        this.selectedFile.set(null);
        if (item.isExpanded && (!item.children || item.children.length === 0)) {
            this.storageApiService
                .list(item.path)
                .pipe(takeUntilDestroyed(this.destroyRef))
                .subscribe({
                    next: (children) => {
                        item.children = this.withPaths(Array.isArray(children) ? children : [], item.path);
                        this.treeData.update((data) => [...data]);
                    },
                    error: () => this.toastService.error(`Failed to load folder "${item.name}"`),
                });
        }
    }

    onContextAction(event: StorageContextActionEvent): void {
        switch (event.action) {
            case 'download':
                if (event.item.type === 'folder') {
                    this.storageApiService
                        .downloadZip([event.item.path])
                        .pipe(takeUntilDestroyed(this.destroyRef))
                        .subscribe({
                            next: (blob) => this.downloadBlobFile(blob, `${event.item.name}.zip`),
                            error: () => this.toastService.error('Failed to download folder'),
                        });
                } else {
                    this.storageApiService.download(event.item.path);
                }
                break;
            case 'delete':
                this.handleDelete(event.item);
                break;
            case 'rename':
                this.handleRename(event);
                break;
            case 'copy':
                this.handleCopy(event.item);
                break;
            case 'duplicate-here':
                this.toastService.info('Duplicate here is coming soon');
                break;
            case 'download-selected':
                this.handleDownloadSelected(event.selectedItems ?? []);
                break;
            case 'delete-selected':
                this.handleDeleteSelected(event.selectedItems ?? []);
                break;
            case 'download-all':
                this.handleDownloadAll();
                break;
            case 'delete-all':
                this.handleDeleteAll();
                break;
            case 'view-details':
                this.handleViewDetails(event.item);
                break;
            case 'add-to-flow':
                this.handleAddToFlow(event.item);
                break;
            case 'move':
                this.handleMove(event);
                break;
        }
    }

    openCreateFolderDialog(folderPath: string = ''): void {
        const data: CreateFolderDialogData = folderPath ? { folderPath } : {};
        const dialogRef = this.dialog.open<CreateFolderDialogResult, CreateFolderDialogData>(
            CreateFolderDialogComponent,
            { data }
        );
        dialogRef.closed.pipe(takeUntilDestroyed(this.destroyRef)).subscribe((result) => {
            if (!result) return;
            if (result.type === 'mkdir') this.toastService.success(`Folder "${result.path}" created`);
            if (result.type === 'upload' && result.count) this.toastService.success(`${result.count} file(s) uploaded`);
            this.reloadTreePreservingExpansion(result.path ? [result.path] : []);
        });
    }

    onFilesDropped(files: FileList): void {
        const dropped = Array.from(files);
        const validFiles = this.filterAllowedFiles(dropped);
        if (!validFiles.length) {
            return;
        }
        this.storageApiService
            .uploadMany('', validFiles)
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe({
                next: () => {
                    this.toastService.success(`${validFiles.length} file(s) uploaded`);
                    this.loadTree();
                },
                error: () => this.toastService.error('Failed to upload files'),
            });
    }

    private handleAddToFlow(item: StorageItem): void {
        const dialogRef = this.dialog.open<AddToFlowDialogResult, AddToFlowDialogData>(AddToFlowDialogComponent, {
            data: { item },
        });
        dialogRef.closed.pipe(takeUntilDestroyed(this.destroyRef)).subscribe((result) => {
            if (!result) return;
            const path = item.type === 'folder' && !item.path.endsWith('/') ? `${item.path}/` : item.path;
            const requests = [];
            if (result.addGraphIds.length) {
                requests.push(this.storageApiService.addToGraph([path], result.addGraphIds));
            }
            if (result.removeGraphIds.length) {
                requests.push(this.storageApiService.removeFromGraph([path], result.removeGraphIds));
            }
            if (!requests.length) return;
            forkJoin(requests)
                .pipe(takeUntilDestroyed(this.destroyRef))
                .subscribe({
                    next: () => this.toastService.success(`"${item.name}" flow assignments updated`),
                    error: () => this.toastService.error(`Failed to update flow assignments for "${item.name}"`),
                });
        });
    }

    private handleCopy(item: StorageItem): void {
        const dialogRef = this.dialog.open<CopyToDialogResult, CopyToDialogData>(CopyToDialogComponent, {
            data: { item },
        });
        dialogRef.closed.pipe(takeUntilDestroyed(this.destroyRef)).subscribe((result) => {
            if (!result) return;
            this.storageApiService
                .copy(item.path, result.toPath)
                .pipe(takeUntilDestroyed(this.destroyRef))
                .subscribe({
                    next: () => {
                        this.toastService.success(`"${item.name}" copied`);
                        this.reloadTreePreservingExpansion(result.toPath ? [result.toPath] : []);
                    },
                    error: () => this.toastService.error(`Failed to copy "${item.name}"`),
                });
        });
    }

    private handleRename(event: { item: StorageItem; renameFromPath?: string }): void {
        const from = event.renameFromPath?.trim() ?? '';
        const to = event.item.path?.trim() ?? '';
        if (!from || !to || from === to) {
            return;
        }
        this.storageApiService
            .rename(from, to)
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe({
                next: () => {
                    this.toastService.success(`Renamed to "${event.item.name}"`);
                    if (this.selectedFile()?.path === from) {
                        this.selectedFile.set(event.item);
                    }
                    const extras = event.item.type === 'folder' ? [to] : [];
                    this.reloadTreePreservingExpansion(extras);
                },
                error: () => this.toastService.error('Failed to rename'),
            });
    }

    private handleMove(event: { item: StorageItem; targetPath?: string }): void {
        const from = event.item.path;
        const to = event.targetPath;
        if (!from || !to || from === to) return;
        this.storageApiService
            .move(from, to)
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe({
                next: () => {
                    this.toastService.success(`"${event.item.name}" moved`);
                    if (this.selectedFile()?.path === from) {
                        this.selectedFile.set({ ...event.item, path: to });
                    }
                    const destination = to === '/' ? '' : to;
                    this.reloadTreePreservingExpansion(destination ? [destination] : []);
                },
                error: () => this.toastService.error(`Failed to move "${event.item.name}"`),
            });
    }

    private handleDelete(item: StorageItem): void {
        if (!item.path) {
            return;
        }

        this.confirmDelete([item])
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe((confirmed) => {
                if (confirmed !== true) {
                    return;
                }

                this.storageApiService
                    .delete([item.path])
                    .pipe(takeUntilDestroyed(this.destroyRef))
                    .subscribe({
                        next: () => {
                            this.toastService.success(`"${item.name}" deleted`);
                            if (this.selectedFile()?.path === item.path) {
                                this.selectedFile.set(null);
                            }
                            this.reloadTreePreservingExpansion();
                        },
                        error: () => this.toastService.error(`Failed to delete "${item.name}"`),
                    });
            });
    }

    private handleViewDetails(item: StorageItem): void {
        this.selectedFile.set(item);
        if (!item.path) {
            return;
        }
        this.storageApiService
            .info(item.path)
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe({
                next: (details) => {
                    this.openDetailsDialog(details, item.path, item.type);
                    this.selectedFile.set({
                        ...item,
                        ...details,
                        path: item.path,
                    });
                },
                error: () => this.toastService.error(`Failed to load details for "${item.name}"`),
            });
    }

    private openDetailsDialog(details: StorageItemInfo, fallbackPath: string, fallbackType: 'file' | 'folder'): void {
        this.dialog.open(StorageDetailsDialogComponent, {
            data: {
                ...details,
                type: details.type ?? fallbackType,
                path: details.path || fallbackPath,
                usedIn: details.graphs ?? [],
                graphs: details.graphs ?? [],
            },
        });
    }

    private handleDownloadSelected(selectedItems: StorageItem[]): void {
        const paths = selectedItems.map((item) => item.path).filter((path): path is string => Boolean(path));
        if (!paths.length) {
            this.toastService.info('Select a file or folder first');
            return;
        }
        this.storageApiService
            .downloadZip(paths)
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe({
                next: (blob) => this.downloadBlobFile(blob, 'selected-items.zip'),
                error: () => this.toastService.error('Failed to download selected items'),
            });
    }

    private handleDeleteSelected(selectedItems: StorageItem[]): void {
        this.deleteItems(selectedItems, 'Selected items deleted', 'Select a file or folder first');
    }

    private handleDownloadAll(): void {
        const paths = this.treeData()
            .map((item) => item.path)
            .filter((path): path is string => Boolean(path));
        if (!paths.length) {
            this.toastService.info('Nothing to download');
            return;
        }
        this.storageApiService
            .downloadZip(paths)
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe({
                next: (blob) => this.downloadBlobFile(blob, 'storage-all.zip'),
                error: () => this.toastService.error('Failed to download all items'),
            });
    }

    private handleDeleteAll(): void {
        const items = this.treeData();
        this.deleteItems(items, 'All items deleted', 'Nothing to delete', true);
    }

    private downloadBlobFile(blob: Blob, filename: string): void {
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = filename;
        a.click();
        URL.revokeObjectURL(url);
    }

    private filterAllowedFiles(files: File[]): File[] {
        const valid: File[] = [];
        for (const file of files) {
            const ext = getFileExtension(file.name);
            const blocked = this.blockedUploadExtensions.has(ext);
            if (!blocked) {
                valid.push(file);
            } else {
                this.toastService.error(`"${file.name}" is not an allowed file type`);
            }
        }
        return valid;
    }

    private deleteItems(
        candidates: StorageItem[],
        successMessage: string,
        emptyMessage: string,
        clearSelectedFile: boolean = false
    ): void {
        const items = candidates.filter((item): item is StorageItem & { path: string } => Boolean(item.path));
        if (!items.length) {
            this.toastService.info(emptyMessage);
            return;
        }

        this.confirmDelete(items)
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe((confirmed) => {
                if (confirmed !== true) {
                    return;
                }

                const paths = items.map((item) => item.path);

                this.storageApiService
                    .delete(paths)
                    .pipe(takeUntilDestroyed(this.destroyRef))
                    .subscribe({
                        next: () => {
                            this.toastService.success(successMessage);
                            if (clearSelectedFile) {
                                this.selectedFile.set(null);
                            } else if (
                                this.selectedFile()?.path &&
                                items.some((item) => item.path === this.selectedFile()?.path)
                            ) {
                                this.selectedFile.set(null);
                            }
                            this.reloadTreePreservingExpansion();
                        },
                        error: () => this.toastService.error(`Failed to delete item(s)`),
                    });
            });
    }

    private confirmDelete(items: StorageItem[]): ReturnType<ConfirmationDialogService['confirm']> {
        const fileCount = items.filter((item) => item.type === 'file').length;
        const folderCount = items.filter((item) => item.type === 'folder').length;
        const isSingle = items.length === 1;

        let title = 'Delete File';
        if (isSingle) {
            title = items[0].type === 'folder' ? 'Delete Folder' : 'Delete File';
        } else if (fileCount > 0 && folderCount === 0) {
            title = 'Delete Files';
        } else if (folderCount > 0 && fileCount === 0) {
            title = 'Delete Folders';
        } else {
            title = 'Delete Files and Folders';
        }

        let message = '';
        if (isSingle) {
            const item = items[0];
            message = `Are you sure you want to delete <strong>${this.escapeHtml(item.name)}</strong> ${item.type}?`;
        } else if (fileCount > 0 && folderCount > 0) {
            message = `Are you sure you want to delete ${this.formatCount(fileCount, 'file', 'files')} and ${this.formatCount(folderCount, 'folder', 'folders')}?`;
        } else if (fileCount > 0) {
            message = `Are you sure you want to delete ${this.formatCount(fileCount, 'file', 'files')}?`;
        } else {
            message = `Are you sure you want to delete ${this.formatCount(folderCount, 'folder', 'folders')}?`;
        }

        return this.confirmationDialogService.confirm({
            title,
            message,
            confirmText: 'Delete',
            cancelText: 'Cancel',
            type: 'danger',
        });
    }

    private formatCount(count: number, single: string, plural: string): string {
        return `${count} ${count === 1 ? single : plural}`;
    }

    private escapeHtml(value: string): string {
        return value
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#39;');
    }
}
