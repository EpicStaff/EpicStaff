import { Dialog } from '@angular/cdk/dialog';
import {
    ChangeDetectionStrategy,
    Component,
    computed,
    DestroyRef,
    effect,
    inject,
    signal,
    ViewChild,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { ActivatedRoute } from '@angular/router';
import { forkJoin } from 'rxjs';
import { finalize } from 'rxjs/operators';

import { ToastService } from '../../../../../../services/notifications/toast.service';
import { ConfirmationDialogService } from '../../../../../../shared/components/cofirm-dialog';
import { DragDropAreaComponent } from '../../../../../../shared/components/drag-drop-area/drag-drop-area.component';
import { SpinnerComponent } from '../../../../../../shared/components/spinner/spinner.component';
import {
    AddToFlowDialogComponent,
    AddToFlowDialogData,
    AddToFlowDialogResult,
} from '../../../../components/add-to-flow-dialog/add-to-flow-dialog.component';
import {
    CopyToDialogComponent,
    CopyToDialogData,
    CopyToDialogResult,
} from '../../../../components/copy-to-dialog/copy-to-dialog.component';
import {
    CreateFolderDialogComponent,
    CreateFolderDialogData,
    CreateFolderDialogResult,
} from '../../../../components/create-folder-dialog/create-folder-dialog.component';
import { StorageDetailsDialogComponent } from '../../../../components/storage-details-dialog/storage-details-dialog.component';
import { StorageItem, StorageItemInfo } from '../../../../models/storage.models';
import { FilesSearchService } from '../../../../services/files-search.service';
import { StorageApiService } from '../../../../services/storage-api.service';
import { StoragePreviewComponent } from './components/storage-preview/storage-preview.component';
import { StorageTreeComponent } from './components/storage-tree/storage-tree.component';

@Component({
    selector: 'app-storage-page',
    imports: [StorageTreeComponent, StoragePreviewComponent, SpinnerComponent, DragDropAreaComponent],
    templateUrl: './storage-page.component.html',
    styleUrls: ['./storage-page.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class StoragePageComponent {
    @ViewChild(StorageTreeComponent) storageTree?: StorageTreeComponent;

    private destroyRef = inject(DestroyRef);
    private storageApiService = inject(StorageApiService);
    private toastService = inject(ToastService);
    private confirmationDialogService = inject(ConfirmationDialogService);
    private dialog = inject(Dialog);
    private filesSearchService = inject(FilesSearchService);
    private route = inject(ActivatedRoute);

    private pendingDeepLinkPath: string | null = null;

    readonly isLoading = signal<boolean>(true);
    readonly treeData = signal<StorageItem[]>([]);
    readonly selectedFile = signal<StorageItem | null>(null);
    readonly selectedItems = signal<StorageItem[]>([]);
    readonly showSidebar = signal<boolean>(true);

    readonly filteredTreeData = computed(() =>
        filterStorageItems(this.treeData(), this.filesSearchService.searchTerm())
    );
    private readonly blockedUploadExtensions = new Set([
        // Windows executables & installers
        'exe',
        'msi',
        'com',
        'scr',
        'pif',
        // Windows scripting
        'bat',
        'cmd',
        'vbs',
        'vbe',
        'wsh',
        'wsf',
        'ps1',
        'psm1',
        'psd1',
        // Unix/macOS executables
        'sh',
        'bash',
        'csh',
        'ksh',
        'zsh',
        'app',
        'command',
        'elf',
        // Java archives (executable)
        'jar',
        'war',
        'ear',
        // Shared libraries
        'dll',
        'so',
        'dylib',
        // Not allowed archive formats
        'rar',
        '7z',
    ]);

    readonly onOpenCreateFolder = (folderPath: string): void => {
        this.openCreateFolderDialog(folderPath);
    };

    toggleSidebar(): void {
        this.showSidebar.update((v) => !v);
    }

    constructor() {
        this.pendingDeepLinkPath = this.route.snapshot.queryParamMap.get('path');

        effect(() => {
            this.storageApiService.refreshTick();
            this.loadTree();
        });
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
                    if (this.pendingDeepLinkPath) {
                        const path = this.pendingDeepLinkPath;
                        this.pendingDeepLinkPath = null;
                        this.expandAndSelectPath(path);
                    }
                },
                error: () => this.toastService.error('Failed to load storage files'),
            });
    }

    private reloadTreePreservingExpansion(extraPathsToExpand: string[] = []): void {
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
        // Sort shallow → deep so parents are loaded before their children are requested.
        const sorted = [...paths].sort((a, b) => a.split('/').length - b.split('/').length);
        for (const path of sorted) {
            this.expandPath(path);
        }
    }

    private expandPath(targetPath: string): void {
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
                this.setSelectedItem(match);
                setTimeout(() => this.storageTree?.selectItemExternally(match));
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

    onFileSelect(item: StorageItem): void {
        this.setSelectedItem(item);
    }

    onFolderSelect(item: StorageItem): void {
        this.setSelectedItem(item);
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

    onPreviewContextAction(event: { action: string; item: StorageItem; selectedItems?: StorageItem[] }): void {
        if (event.action === 'rename') {
            if (!this.showSidebar()) {
                this.showSidebar.set(true);
                setTimeout(() => this.storageTree?.startRename(event.item));
            } else {
                this.storageTree?.startRename(event.item);
            }
        } else {
            this.onContextAction(event);
        }
    }

    onContextAction(event: {
        action: string;
        item: StorageItem;
        selectedItems?: StorageItem[];
        renameFromPath?: string;
        targetPath?: string;
    }): void {
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
                // TODO: Implement duplicate in current folder
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
                    // If the renamed item is itself a folder, re-expand it under its new path.
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
                    // Expand the destination so the moved item is visible.
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
            const lowerName = file.name.toLowerCase();
            const ext = lowerName.includes('.') ? (lowerName.split('.').pop() ?? '') : '';
            const blocked = this.blockedUploadExtensions.has(ext);
            if (!blocked) {
                valid.push(file);
            } else {
                this.toastService.error(`"${file.name}" is not an allowed file type`);
            }
        }
        return valid;
    }

    private setSelectedItem(item: StorageItem): void {
        this.selectedFile.set(item);
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

function filterStorageItems(items: StorageItem[], term: string): StorageItem[] {
    if (!term.trim()) return items;
    const lower = term.toLowerCase();
    const result: StorageItem[] = [];
    for (const item of items) {
        if (item.type === 'folder') {
            const filteredChildren = filterStorageItems(item.children ?? [], lower);
            if (filteredChildren.length || item.name.toLowerCase().includes(lower)) {
                result.push({ ...item, children: filteredChildren, isExpanded: filteredChildren.length > 0 });
            }
        } else {
            if (item.name.toLowerCase().includes(lower)) result.push(item);
        }
    }
    return result;
}
