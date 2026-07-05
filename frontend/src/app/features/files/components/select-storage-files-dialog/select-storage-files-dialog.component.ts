import { Dialog, DIALOG_DATA, DialogRef } from '@angular/cdk/dialog';
import { ChangeDetectionStrategy, Component, computed, DestroyRef, inject, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { FormsModule } from '@angular/forms';
import { MatTooltipModule } from '@angular/material/tooltip';
import { forkJoin } from 'rxjs';

import { ToastService } from '../../../../services/notifications/toast.service';
import { AppSvgIconComponent } from '../../../../shared/components/app-svg-icon/app-svg-icon.component';
import { ConfirmationDialogService } from '../../../../shared/components/cofirm-dialog';
import { Spinner2Component } from '../../../../shared/components/spinner-type2/spinner.component';
import { GraphFileRecord } from '../../models/storage.models';
import { StorageApiService } from '../../services/storage-api.service';
import { getFileExtension } from '../../utils/storage-file.utils';
import {
    CreateFolderDialogComponent,
    CreateFolderDialogResult,
} from '../create-folder-dialog/create-folder-dialog.component';

export interface SelectStorageFilesDialogData {
    flowId: number;
    flowName: string;
}

export interface SelectStorageFilesDialogResult {
    changed: boolean;
}

interface TreeNode {
    name: string;
    path: string;
    type: 'file' | 'folder';
    level: number;
    isExpanded: boolean;
    isLoading: boolean;
    hasChildren: boolean;
    children: TreeNode[];
    isLoaded: boolean;
    is_empty?: boolean;
    size?: number;
}

@Component({
    selector: 'app-select-storage-files-dialog',
    imports: [FormsModule, AppSvgIconComponent, Spinner2Component, MatTooltipModule],
    templateUrl: './select-storage-files-dialog.component.html',
    styleUrls: ['./select-storage-files-dialog.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class SelectStorageFilesDialogComponent {
    private readonly dialogRef = inject<DialogRef<SelectStorageFilesDialogResult | undefined>>(DialogRef);
    private readonly data: SelectStorageFilesDialogData = inject(DIALOG_DATA);
    private readonly storageApiService = inject(StorageApiService);
    private readonly confirmationDialogService = inject(ConfirmationDialogService);
    private readonly toastService = inject(ToastService);
    private readonly dialog = inject(Dialog);
    private readonly destroyRef = inject(DestroyRef);

    readonly flowId = this.data.flowId;
    readonly flowName = this.data.flowName;

    readonly attachedFiles = signal<GraphFileRecord[]>([]);

    readonly attachedFilePaths = computed(
        () =>
            new Set(
                this.attachedFiles()
                    .filter((f) => !f.path.endsWith('/'))
                    .map((f) => f.path)
            )
    );

    readonly attachedFolderPaths = computed(
        () =>
            new Set(
                this.attachedFiles()
                    .filter((f) => f.path.endsWith('/'))
                    .map((f) => f.path.replace(/\/+$/, ''))
            )
    );

    readonly searchQuery = signal('');
    readonly rootNodes = signal<TreeNode[]>([]);
    readonly isLoadingRoot = signal(true);
    readonly isSaving = signal(false);

    readonly selectedFilePaths = signal<Set<string>>(new Set());

    readonly selectedFolderPaths = signal<Set<string>>(new Set());

    private hasMadeChanges = false;

    private readonly allNodes = signal<TreeNode[]>([]);

    readonly visibleNodes = computed(() => {
        const query = this.searchQuery().toLowerCase().trim();
        const all = this.allNodes();
        if (query) {
            const filtered = all.filter((n) => n.name.toLowerCase().includes(query));
            const minLevel = filtered.reduce((min, n) => Math.min(min, n.level), Infinity);
            return filtered.map((n) => ({ ...n, level: n.level - minLevel }));
        }
        return this.buildVisible(this.rootNodes());
    });

    readonly hasChanges = computed(() => {
        const selectedFiles = this.selectedFilePaths();
        const attachedFiles = this.attachedFilePaths();
        if (selectedFiles.size !== attachedFiles.size) return true;
        for (const p of selectedFiles) if (!attachedFiles.has(p)) return true;

        const selectedFolders = this.selectedFolderPaths();
        const attachedFolders = this.attachedFolderPaths();
        if (selectedFolders.size !== attachedFolders.size) return true;
        for (const p of selectedFolders) if (!attachedFolders.has(p)) return true;

        return false;
    });

    readonly selectedSizeLabel = computed(() => {
        const selected = this.selectedFilePaths();
        const all = this.allNodes();

        const sizeByPath = new Map<string, number>();
        for (const n of all) {
            if (n.type === 'file' && n.size != null) sizeByPath.set(n.path, n.size);
        }

        let totalBytes = 0;
        for (const p of selected) {
            const size = sizeByPath.get(p);
            if (size != null) totalBytes += size;
        }
        return this.formatSize(totalBytes);
    });

    formatSize(bytes: number): string {
        if (bytes < 1024) return `${bytes} B`;
        if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
        return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
    }

    ngOnInit(): void {
        this.loadAttachedFiles(() => {
            this.selectedFilePaths.set(new Set(this.attachedFilePaths()));
            this.selectedFolderPaths.set(new Set(this.attachedFolderPaths()));
            this.loadLevel('', null, () => this.expandToAttachedPaths());
        });
    }

    toggleExpand(event: Event, node: TreeNode): void {
        event.stopPropagation();
        if (node.isExpanded) {
            node.isExpanded = false;
        } else {
            node.isExpanded = true;
            if (!node.isLoaded && node.hasChildren) {
                node.isLoading = true;
                this.loadLevel(node.path, node);
            }
        }
        this.rootNodes.update((n) => [...n]);
        this.rebuildAllNodes();
    }

    toggleCheck(node: TreeNode): void {
        if (node.type === 'file') {
            const wasChecked = this.selectedFilePaths().has(node.path);
            this.selectedFilePaths.update((set) => {
                const next = new Set(set);
                if (wasChecked) next.delete(node.path);
                else next.add(node.path);
                return next;
            });
            if (wasChecked) this.clearAncestorFolders(node.path);
            return;
        }

        this.ensureLoaded(node, () => {
            const checked = this.isChecked(node);
            const descendants = this.collectFilePaths(node);

            this.selectedFolderPaths.update((set) => {
                const next = new Set(set);
                if (checked) next.delete(node.path);
                else next.add(node.path);
                return next;
            });

            if (descendants.length > 0) {
                this.selectedFilePaths.update((set) => {
                    const next = new Set(set);
                    if (checked) {
                        for (const p of descendants) next.delete(p);
                    } else {
                        for (const p of descendants) next.add(p);
                    }
                    return next;
                });
            }

            if (checked) this.clearAncestorFolders(node.path);
        });
    }

    private clearAncestorFolders(path: string): void {
        const parts = path.split('/').filter(Boolean);
        if (parts.length <= 1) return;
        const ancestors = new Set<string>();
        for (let i = 1; i < parts.length; i++) {
            ancestors.add(parts.slice(0, i).join('/'));
        }
        this.selectedFolderPaths.update((set) => {
            let changed = false;
            const next = new Set(set);
            for (const a of ancestors) {
                if (next.delete(a)) changed = true;
            }
            return changed ? next : set;
        });
    }

    isChecked(node: TreeNode): boolean {
        if (node.type === 'file') return this.selectedFilePaths().has(node.path);
        if (this.selectedFolderPaths().has(node.path)) return true;
        const files = this.collectFilePaths(node);
        if (files.length === 0) return false;
        const selected = this.selectedFilePaths();
        return files.every((p) => selected.has(p));
    }

    isIndeterminate(node: TreeNode): boolean {
        if (node.type !== 'folder') return false;
        if (this.selectedFolderPaths().has(node.path)) return false;
        const files = this.collectFilePaths(node);
        if (files.length === 0) return false;
        const selected = this.selectedFilePaths();
        const matched = files.filter((p) => selected.has(p)).length;
        return matched > 0 && matched < files.length;
    }

    onConfirm(): void {
        if (!this.hasChanges() || this.isSaving()) {
            this.dialogRef.close({ changed: this.hasMadeChanges });
            return;
        }

        const { checks, unchecks } = this.computeDiff();

        if (unchecks.length > 0) {
            const flowName = this.escapeHtml(this.flowName);
            let title: string;
            let message: string;

            if (unchecks.length === 1) {
                const fileName = this.escapeHtml(this.getFileName(unchecks[0]));
                title = 'Remove File?';
                message = `Are you sure you want to remove <strong>${fileName}</strong> file from the <strong>${flowName}</strong> flow?`;
            } else {
                title = 'Remove Files?';
                message = `Are you sure you want to remove <strong>${unchecks.length} files</strong> from the <strong>${flowName}</strong> flow?`;
            }

            this.confirmationDialogService
                .confirm({
                    title,
                    message,
                    confirmText: 'Remove',
                    cancelText: 'Cancel',
                    type: 'warning',
                })
                .pipe(takeUntilDestroyed(this.destroyRef))
                .subscribe((confirmed) => {
                    if (confirmed === true) this.executeSave(checks, unchecks);
                });
        } else {
            this.executeSave(checks, unchecks);
        }
    }

    private computeDiff(): { checks: string[]; unchecks: string[] } {
        const checks: string[] = [];
        const unchecks: string[] = [];

        const selectedFiles = this.selectedFilePaths();
        const attachedFiles = this.attachedFilePaths();
        for (const p of selectedFiles) if (!attachedFiles.has(p)) checks.push(p);
        for (const p of attachedFiles) if (!selectedFiles.has(p)) unchecks.push(p);

        const selectedFolders = this.selectedFolderPaths();
        const attachedFolders = this.attachedFolderPaths();
        for (const p of selectedFolders) if (!attachedFolders.has(p)) checks.push(`${p}/`);
        for (const p of attachedFolders) if (!selectedFolders.has(p)) unchecks.push(`${p}/`);

        return { checks, unchecks };
    }

    private executeSave(checks: string[], unchecks: string[]): void {
        this.isSaving.set(true);

        const requests = [
            ...(checks.length ? [this.storageApiService.addToGraph(checks, [this.flowId])] : []),
            ...(unchecks.length ? [this.storageApiService.removeFromGraph(unchecks, [this.flowId])] : []),
        ];

        if (requests.length === 0) {
            this.isSaving.set(false);
            this.dialogRef.close({ changed: this.hasMadeChanges });
            return;
        }

        forkJoin(requests)
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe({
                next: () => {
                    this.isSaving.set(false);
                    this.hasMadeChanges = true;
                    this.toastService.success('Files updated successfully');
                    this.dialogRef.close({ changed: true });
                },
                error: () => {
                    this.isSaving.set(false);
                    this.toastService.error('Failed to update files');
                },
            });
    }

    onCancel(): void {
        this.dialogRef.close({ changed: this.hasMadeChanges });
    }

    onAddFilesToStorage(): void {
        const ref = this.dialog.open<CreateFolderDialogResult>(CreateFolderDialogComponent, {
            data: {},
        });

        ref.closed.pipe(takeUntilDestroyed(this.destroyRef)).subscribe((result) => {
            if (!result) return;
            this.reloadTree();
        });
    }

    private reloadTree(): void {
        this.rootNodes.set([]);
        this.allNodes.set([]);
        this.isLoadingRoot.set(true);
        this.loadLevel('', null);
    }

    getFileIcon(node: TreeNode): string {
        if (node.type === 'folder') return 'folder-storage';
        const ext = getFileExtension(node.name);
        if (ext === 'txt') return 'file-txt';
        if (ext === 'pdf') return 'file-pdf';
        if (ext === 'docx') return 'file-docx';
        if (ext === 'json') return 'file-json';
        if (ext === 'html') return 'file-html';
        return 'file';
    }

    private loadAttachedFiles(onDone?: () => void): void {
        this.storageApiService
            .getGraphFiles(this.flowId)
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe({
                next: (files) => {
                    this.attachedFiles.set(files);
                    onDone?.();
                },
                error: () => {
                    this.attachedFiles.set([]);
                    onDone?.();
                },
            });
    }

    private loadLevel(path: string, parent: TreeNode | null, onDone?: () => void): void {
        this.storageApiService
            .list(path)
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe({
                next: (items) => {
                    const nodes: TreeNode[] = items.map((i) => ({
                        name: i.name,
                        path: i.path || (path ? `${path}/${i.name}` : i.name),
                        type: i.type,
                        level: parent ? parent.level + 1 : 0,
                        isExpanded: false,
                        isLoading: false,
                        hasChildren: i.type === 'folder' && !i.is_empty,
                        children: [],
                        isLoaded: false,
                        is_empty: i.is_empty,
                        size: i.size,
                    }));

                    if (parent) {
                        parent.children = nodes;
                        parent.isLoaded = true;
                        parent.isLoading = false;
                        parent.hasChildren = nodes.length > 0;
                    } else {
                        this.rootNodes.set(nodes);
                        this.isLoadingRoot.set(false);
                    }

                    this.rebuildAllNodes();
                    this.rootNodes.update((n) => [...n]);
                    onDone?.();
                },
                error: () => {
                    if (parent) {
                        parent.isLoading = false;
                        parent.isLoaded = true;
                    } else {
                        this.isLoadingRoot.set(false);
                    }
                    this.rootNodes.update((n) => [...n]);
                    onDone?.();
                },
            });
    }

    /** Recursively load all descendants of a folder, then invoke callback. */
    private ensureLoaded(node: TreeNode, onDone: () => void): void {
        if (node.type !== 'folder' || !node.hasChildren) {
            onDone();
            return;
        }

        const loadChildren = (n: TreeNode, cb: () => void): void => {
            if (n.type !== 'folder' || !n.hasChildren) {
                cb();
                return;
            }
            if (!n.isLoaded) {
                n.isLoading = true;
                this.loadLevel(n.path, n, () => {
                    n.isLoading = false;
                    loadAllChildren(n.children, cb);
                });
            } else {
                loadAllChildren(n.children, cb);
            }
        };

        const loadAllChildren = (children: TreeNode[], cb: () => void): void => {
            const folders = children.filter((c) => c.type === 'folder' && c.hasChildren);
            if (folders.length === 0) {
                cb();
                return;
            }
            let remaining = folders.length;
            for (const f of folders) {
                loadChildren(f, () => {
                    remaining--;
                    if (remaining === 0) cb();
                });
            }
        };

        loadChildren(node, onDone);
    }

    private expandToAttachedPaths(): void {
        const ancestorPaths = new Set<string>();
        for (const file of this.attachedFiles()) {
            const parts = file.path.split('/').filter(Boolean);
            for (let i = 1; i < parts.length; i++) {
                ancestorPaths.add(parts.slice(0, i).join('/'));
            }
        }

        const tryExpand = (): void => {
            for (const path of ancestorPaths) {
                const node = this.findNodeByPath(this.rootNodes(), path);
                if (!node || node.type !== 'folder') continue;
                if (node.isExpanded && node.isLoaded) continue;

                node.isExpanded = true;

                if (!node.isLoaded && node.hasChildren) {
                    node.isLoading = true;
                    this.loadLevel(node.path, node, () => tryExpand());
                }
            }
            this.rootNodes.update((n) => [...n]);
            this.rebuildAllNodes();
        };

        tryExpand();
    }

    private findNodeByPath(nodes: TreeNode[], path: string): TreeNode | null {
        for (const n of nodes) {
            if (n.path === path) return n;
            if (n.children.length > 0) {
                const found = this.findNodeByPath(n.children, path);
                if (found) return found;
            }
        }
        return null;
    }

    private collectFilePaths(node: TreeNode): string[] {
        if (node.type === 'file') return [node.path];
        const result: string[] = [];
        const walk = (n: TreeNode) => {
            if (n.type === 'file') {
                result.push(n.path);
                return;
            }
            for (const child of n.children) walk(child);
        };
        walk(node);
        return result;
    }

    private buildVisible(nodes: TreeNode[]): TreeNode[] {
        const result: TreeNode[] = [];
        for (const node of nodes) {
            result.push(node);
            if (node.isExpanded && node.children.length > 0) {
                result.push(...this.buildVisible(node.children));
            }
        }
        return result;
    }

    private rebuildAllNodes(): void {
        const flatten = (nodes: TreeNode[]): TreeNode[] => {
            const result: TreeNode[] = [];
            for (const node of nodes) {
                result.push(node);
                if (node.children.length > 0) {
                    result.push(...flatten(node.children));
                }
            }
            return result;
        };
        this.allNodes.set(flatten(this.rootNodes()));
    }

    private getFileName(path: string): string {
        const parts = path.replace(/\/+$/, '').split('/');
        return parts[parts.length - 1] || path;
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
