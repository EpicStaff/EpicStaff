import { Dialog } from '@angular/cdk/dialog';
import { HttpErrorResponse } from '@angular/common/http';
import { computed, DestroyRef, effect, inject, Injectable, signal, untracked } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { ConfirmationDialogService } from '@shared/components';
import { downloadBlob } from '@shared/utils';
import { EMPTY, forkJoin, from, Observable, of, Subject } from 'rxjs';
import { catchError, concatMap, finalize, map, switchMap, toArray } from 'rxjs/operators';

import { ToastService } from '../../../services/notifications';
import {
    ADD_TO_COLLECTION_DIALOG_TITLE_ID,
    AddToCollectionDialogComponent,
    AddToCollectionDialogData,
} from '../../knowledge-sources/components/add-to-collection-dialog/add-to-collection-dialog.component';
import { extractStorageFileIds } from '../../knowledge-sources/helpers/storage-import.util';
import { ImportFromStorageResponse } from '../../knowledge-sources/models/document.model';
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

/** `initial` shows the page error state on failure; `preserving` only toasts. */
interface TreeRefreshRequest {
    kind: 'initial' | 'preserving';
    extraPathsToExpand: string[];
    onDone?: () => void;
}

interface MoveOutcome {
    moved: StorageItem[];
    failed: StorageItem[];
}

@Injectable()
export class StorageTreeFacade {
    private destroyRef = inject(DestroyRef);
    private storageApiService = inject(StorageApiService);
    private toastService = inject(ToastService);
    private confirmationDialogService = inject(ConfirmationDialogService);
    private dialog = inject(Dialog);

    readonly isLoading = signal<boolean>(true);
    /** True only until the first tree load settles; later refreshes keep the tree (and any drag source) mounted. */
    readonly isInitialLoading = computed(() => this.isLoading() && !this.hasLoadedOnce());
    readonly error = signal<string | null>(null);
    readonly treeData = signal<StorageItem[]>([]);
    readonly selectedFile = signal<StorageItem | null>(null);
    readonly selectedItems = signal<StorageItem[]>([]);

    readonly selectInTree = new Subject<StorageItem>();
    readonly renameInTree = new Subject<StorageItem>();

    afterTreeLoad: (() => void) | null = null;

    private readonly hasLoadedOnce = signal<boolean>(false);
    private readonly refreshRequests = new Subject<TreeRefreshRequest>();
    private watchRefreshTick = false;
    private suppressNextTick = false;

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
        this.subscribeToRefreshRequests();
        effect(() => {
            this.storageApiService.refreshTick();
            if (this.suppressNextTick) {
                this.suppressNextTick = false;
                return;
            }
            if (!this.watchRefreshTick) return;
            // loadTree reads treeData synchronously (switchMap), which must not become a dependency.
            untracked(() => this.loadTree());
        });
    }

    init(options: { watchRefreshTick: boolean }): void {
        this.watchRefreshTick = options.watchRefreshTick;
    }

    private notifyStorageChanged(): void {
        this.suppressNextTick = true;
        this.storageApiService.triggerRefresh();
    }

    loadTree(): void {
        this.error.set(null);
        this.requestRefresh({ kind: 'initial', extraPathsToExpand: [] });
    }

    /**
     * Refreshes the tree in place: expanded folders stay expanded with their children refreshed,
     * so existing rows (including a row being dragged) stay mounted. `extraPathsToExpand` are
     * expanded afterwards (e.g. a move destination).
     */
    reloadTreePreservingExpansion(extraPathsToExpand: string[] = [], onDone?: () => void): void {
        this.requestRefresh({ kind: 'preserving', extraPathsToExpand, onDone });
    }

    private requestRefresh(request: TreeRefreshRequest): void {
        this.isLoading.set(true);
        this.refreshRequests.next(request);
    }

    /**
     * One pipeline for every refresh: `switchMap` unsubscribes an outdated refresh, which cancels
     * its HTTP requests (nested levels included), so an older result or error can never land.
     * `isLoading` is only reset by the refresh that actually finishes.
     */
    private subscribeToRefreshRequests(): void {
        this.refreshRequests
            .pipe(
                switchMap((request) =>
                    this.fetchMergedLevel('', this.treeData()).pipe(
                        map((roots) => ({ request, roots })),
                        catchError(() => {
                            this.isLoading.set(false);
                            if (request.kind === 'initial') {
                                this.error.set('Failed to load storage files');
                            } else {
                                this.toastService.error('Failed to load storage files');
                            }
                            return EMPTY;
                        })
                    )
                ),
                takeUntilDestroyed(this.destroyRef)
            )
            .subscribe(({ request, roots }) => {
                this.treeData.set(roots);
                this.hasLoadedOnce.set(true);
                this.isLoading.set(false);
                if (request.kind === 'initial') {
                    this.afterTreeLoad?.();
                    return;
                }
                this.notifyStorageChanged();
                this.restoreExpandedPaths(request.extraPathsToExpand.filter(Boolean), () => request.onDone?.());
            });
    }

    /**
     * Lists one level and merges it with the previous nodes of that level by path. Expanded
     * folders keep `isExpanded` and have their children refreshed recursively; collapsed folders
     * drop their children so they reload on the next expand. Builds new node objects and never
     * mutates the current tree, so an outdated refresh can simply be discarded.
     * Known limitation: an expand/collapse made while a refresh is in flight is lost (the result wins).
     */
    private fetchMergedLevel(path: string, previous: StorageItem[]): Observable<StorageItem[]> {
        const previousByPath = new Map(previous.map((node) => [node.path, node]));
        return this.storageApiService.list(path).pipe(
            switchMap((items) => {
                const merged = this.withPaths(Array.isArray(items) ? items : [], path).map((fresh) => {
                    const old = previousByPath.get(fresh.path);
                    const keepExpanded = fresh.type === 'folder' && old?.type === 'folder' && !!old.isExpanded;
                    if (!keepExpanded) return fresh;
                    return { ...fresh, isExpanded: true, children: fresh.is_empty ? [] : old?.children };
                });
                const expanded = merged.filter((node) => node.isExpanded && !node.is_empty);
                if (expanded.length === 0) return of(merged);
                return forkJoin(
                    expanded.map((folder) =>
                        this.fetchMergedLevel(folder.path, folder.children ?? []).pipe(
                            // A failed sub-level keeps what it showed before instead of failing the refresh.
                            catchError(() => of(folder.children ?? [])),
                            map((children) => {
                                folder.children = children;
                            })
                        )
                    )
                ).pipe(map(() => merged));
            })
        );
    }

    private restoreExpandedPaths(paths: string[], onAllDone?: () => void): void {
        const sorted = [...paths].sort((a, b) => a.split('/').length - b.split('/').length);
        if (sorted.length === 0) {
            onAllDone?.();
            return;
        }
        let remaining = sorted.length;
        const onOneDone = (): void => {
            remaining -= 1;
            if (remaining <= 0) onAllDone?.();
        };
        for (const path of sorted) {
            this.expandPath(path, onOneDone);
        }
    }

    expandPath(targetPath: string, onDone?: () => void): void {
        const segments = targetPath.split('/').filter(Boolean);
        if (!segments.length) {
            onDone?.();
            return;
        }

        const walk = (index: number, nodes: StorageItem[], currentPath: string): void => {
            const segment = segments[index];
            const nextPath = currentPath ? `${currentPath}/${segment}` : segment;
            const match = nodes.find((n) => n.name === segment);
            if (!match || match.type !== 'folder') {
                onDone?.();
                return;
            }

            match.isExpanded = true;
            const isLast = index === segments.length - 1;

            if (!match.children || match.children.length === 0) {
                if (match.is_empty) {
                    this.treeData.update((data) => [...data]);
                    onDone?.();
                    return;
                }
                this.storageApiService
                    .list(nextPath)
                    .pipe(takeUntilDestroyed(this.destroyRef))
                    .subscribe({
                        next: (children) => {
                            match.children = this.withPaths(Array.isArray(children) ? children : [], nextPath);
                            this.treeData.update((data) => [...data]);
                            if (!isLast) {
                                walk(index + 1, match.children ?? [], nextPath);
                            } else {
                                onDone?.();
                            }
                        },
                        error: () => onDone?.(),
                    });
            } else {
                this.treeData.update((data) => [...data]);
                if (!isLast) {
                    walk(index + 1, match.children, nextPath);
                } else {
                    onDone?.();
                }
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
                            next: (blob) => downloadBlob(blob, `${event.item.name}.zip`),
                            error: () => this.toastService.error('Failed to download folder'),
                        });
                } else {
                    this.storageApiService
                        .downloadBlob(event.item.path)
                        .pipe(takeUntilDestroyed(this.destroyRef))
                        .subscribe({
                            next: (blob) => downloadBlob(blob, event.item.name),
                            error: () => this.toastService.error(`Failed to download "${event.item.name}"`),
                        });
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
            case 'group-selected':
                this.handleGroupSelected(event);
                break;
            case 'add-to-collection':
                this.handleAddToCollection(event);
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
            .confirmOverwrite('', validFiles)
            .pipe(
                switchMap((confirmed) => (confirmed ? this.storageApiService.uploadMany('', validFiles) : EMPTY)),
                takeUntilDestroyed(this.destroyRef)
            )
            .subscribe({
                next: () => {
                    this.toastService.success(`${validFiles.length} file(s) uploaded`);
                    this.loadTree();
                    this.notifyStorageChanged();
                },
                error: (error: unknown) => {
                    const checking = error instanceof HttpErrorResponse && error.url?.includes('/storage/list/');
                    this.toastService.error(checking ? 'Failed to check existing files' : 'Failed to upload files');
                },
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

    private handleMove(event: { item: StorageItem; selectedItems?: StorageItem[]; targetPath?: string }): void {
        const to = event.targetPath;
        if (!to) return;

        const items = (event.selectedItems?.length ? event.selectedItems : [event.item]).filter(
            (item) => Boolean(item.path) && item.path !== to
        );
        if (items.length === 0) return;

        const destination = to === '/' ? '' : to;
        this.moveSequentially(items, to)
            .pipe(
                finalize(() => {
                    if (this.destroyRef.destroyed) return;
                    this.reloadTreePreservingExpansion(destination ? [destination] : []);
                }),
                takeUntilDestroyed(this.destroyRef)
            )
            .subscribe((outcome) => {
                this.clearSelectedFileIfMoved(outcome.moved);
                this.notifyMoveOutcome(outcome, {
                    success: items.length === 1 ? `"${items[0].name}" moved` : `${items.length} items moved`,
                    failure: items.length === 1 ? `Failed to move "${items[0].name}"` : 'Failed to move selected items',
                    partial: `${outcome.moved.length} of ${items.length} items moved`,
                });
            });
    }

    private handleGroupSelected(event: { selectedItems?: StorageItem[] }): void {
        const items = event.selectedItems ?? [];
        if (items.length < 2) return;

        const parentPath = this.getParentPath(items[0].path);
        const name = this.buildUniqueFolderName(parentPath);
        const targetPath = parentPath ? `${parentPath}/${name}` : name;
        let movedCount = 0;

        this.storageApiService
            .mkdir(targetPath)
            .pipe(
                switchMap(() => this.moveSequentially(items, targetPath)),
                switchMap((outcome) =>
                    outcome.moved.length > 0
                        ? of(outcome)
                        : this.removeFolderIfEmpty(targetPath).pipe(map(() => outcome))
                ),
                finalize(() => {
                    if (this.destroyRef.destroyed) return;
                    const renameNewFolder =
                        movedCount > 0 ? () => this.triggerRenameForNewFolder(targetPath) : undefined;
                    this.reloadTreePreservingExpansion([targetPath], renameNewFolder);
                }),
                takeUntilDestroyed(this.destroyRef)
            )
            .subscribe({
                next: (outcome) => {
                    movedCount = outcome.moved.length;
                    this.clearSelectedFileIfMoved(outcome.moved);
                    this.notifyMoveOutcome(outcome, {
                        success: `${items.length} items grouped into "${name}"`,
                        failure: 'Failed to group items',
                        partial: `${outcome.moved.length} of ${items.length} items grouped into "${name}"`,
                    });
                },
                error: () => this.toastService.error('Failed to group items'),
            });
    }

    /**
     * One `move/` request at a time, never in parallel: parallel moves of two same-named files
     * into one folder race on the server's name dedup. A failed item does not stop the rest.
     */
    private moveSequentially(items: StorageItem[], to: string): Observable<MoveOutcome> {
        return from(items).pipe(
            concatMap((item) =>
                this.storageApiService.move(item.path, to).pipe(
                    map(() => ({ item, moved: true })),
                    catchError(() => of({ item, moved: false }))
                )
            ),
            toArray(),
            map((results) => ({
                moved: results.filter((result) => result.moved).map((result) => result.item),
                failed: results.filter((result) => !result.moved).map((result) => result.item),
            }))
        );
    }

    /**
     * Deletes the folder only when the server reports it empty. A move that failed on the client
     * (timeout, 504) may still have been applied, and delete is recursive — so never delete blindly.
     * Any error leaves the folder in place.
     */
    private removeFolderIfEmpty(folderPath: string): Observable<void> {
        return this.storageApiService.list(folderPath).pipe(
            switchMap((children) =>
                children.length === 0 ? this.storageApiService.delete([folderPath]) : of(undefined)
            ),
            catchError(() => of(undefined))
        );
    }

    private notifyMoveOutcome(
        outcome: MoveOutcome,
        messages: { success: string; failure: string; partial: string }
    ): void {
        if (outcome.failed.length === 0) {
            this.toastService.success(messages.success);
        } else if (outcome.moved.length === 0) {
            this.toastService.error(messages.failure);
        } else {
            this.toastService.warning(`${messages.partial}. Failed: ${this.formatNameList(outcome.failed)}`);
        }
    }

    private clearSelectedFileIfMoved(moved: StorageItem[]): void {
        const selected = this.selectedFile();
        if (selected && moved.some((item) => item.path === selected.path)) {
            this.selectedFile.set(null);
        }
    }

    private formatNameList(items: StorageItem[], maxNames = 3): string {
        const names = items.slice(0, maxNames).map((item) => `"${item.name}"`);
        const rest = items.length - names.length;
        return rest > 0 ? `${names.join(', ')} and ${rest} more` : names.join(', ');
    }

    private handleAddToCollection(event: { item: StorageItem; selectedItems?: StorageItem[] }): void {
        const items = event.selectedItems?.length ? event.selectedItems : [event.item];
        // Unresolvable items are reported by DocumentsStorageService when the import runs.
        if (extractStorageFileIds(items).storageFileIds.length === 0) {
            this.toastService.error('None of the selected items could be added');
            return;
        }
        this.dialog.open<ImportFromStorageResponse, AddToCollectionDialogData>(AddToCollectionDialogComponent, {
            data: { items },
            ariaLabelledBy: ADD_TO_COLLECTION_DIALOG_TITLE_ID,
        });
    }

    private triggerRenameForNewFolder(targetPath: string, retriesLeft = 20): void {
        const node = this.findNodeByPath(this.treeData(), targetPath);
        if (node) {
            this.renameInTree.next(node);
            return;
        }
        if (retriesLeft <= 0) return;
        setTimeout(() => this.triggerRenameForNewFolder(targetPath, retriesLeft - 1), 150);
    }

    private findNodeByPath(nodes: StorageItem[], path: string): StorageItem | undefined {
        for (const node of nodes) {
            if (node.path === path) return node;
            if (node.children?.length) {
                const found = this.findNodeByPath(node.children, path);
                if (found) return found;
            }
        }
        return undefined;
    }

    private buildUniqueFolderName(parentPath: string): string {
        const parent = parentPath ? this.findNodeByPath(this.treeData(), parentPath) : undefined;
        const siblings = parentPath ? (parent?.children ?? []) : this.treeData();
        const existingNames = new Set(siblings.map((item) => item.name));

        if (!existingNames.has('New Folder')) {
            return 'New Folder';
        }
        let counter = 2;
        while (existingNames.has(`New Folder (${counter})`)) {
            counter += 1;
        }
        return `New Folder (${counter})`;
    }

    private getParentPath(path: string): string {
        const idx = path.lastIndexOf('/');
        return idx >= 0 ? path.substring(0, idx) : '';
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
                next: (blob) => downloadBlob(blob, 'selected-items.zip'),
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
                next: (blob) => downloadBlob(blob, 'storage-all.zip'),
                error: () => this.toastService.error('Failed to download all items'),
            });
    }

    private handleDeleteAll(): void {
        const items = this.treeData();
        this.deleteItems(items, 'All items deleted', 'Nothing to delete', true);
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
