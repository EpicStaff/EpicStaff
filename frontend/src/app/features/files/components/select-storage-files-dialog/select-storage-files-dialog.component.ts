import { Dialog, DIALOG_DATA, DialogRef } from '@angular/cdk/dialog';
import { ChangeDetectionStrategy, Component, computed, DestroyRef, inject, OnInit, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { FormsModule } from '@angular/forms';
import { MatTooltipModule } from '@angular/material/tooltip';
import { EMPTY, forkJoin, switchMap } from 'rxjs';

import { ToastService } from '../../../../services/notifications/toast.service';
import { AppSvgIconComponent } from '../../../../shared/components/app-svg-icon/app-svg-icon.component';
import { ConfirmationDialogService } from '../../../../shared/components/cofirm-dialog';
import { DragDropAreaComponent } from '../../../../shared/components/drag-drop-area/drag-drop-area.component';
import { Spinner2Component } from '../../../../shared/components/spinner-type2/spinner.component';
import { FileSizePipe } from '../../../../shared/pipes/file-size.pipe';
import { GraphFileRecord, StorageTreeNode } from '../../models/storage.models';
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
    hasChildren: boolean;
    children: TreeNode[];
    size?: number;
}

@Component({
    selector: 'app-select-storage-files-dialog',
    imports: [
        FormsModule,
        AppSvgIconComponent,
        Spinner2Component,
        MatTooltipModule,
        FileSizePipe,
        DragDropAreaComponent,
    ],
    templateUrl: './select-storage-files-dialog.component.html',
    styleUrls: ['./select-storage-files-dialog.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class SelectStorageFilesDialogComponent implements OnInit {
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
    readonly isUploading = signal(false);

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
        const selectedFolders = this.selectedFolderPaths();
        const attachedFolders = this.attachedFolderPaths();
        if (selectedFolders.size !== attachedFolders.size) return true;
        for (const p of selectedFolders) if (!attachedFolders.has(p)) return true;

        const selectedFiles = this.filesNotCoveredByFolders(this.selectedFilePaths(), selectedFolders);
        const attachedFiles = this.filesNotCoveredByFolders(this.attachedFilePaths(), attachedFolders);
        if (selectedFiles.size !== attachedFiles.size) return true;
        for (const p of selectedFiles) if (!attachedFiles.has(p)) return true;

        return false;
    });

    readonly selectedSizeBytes = computed(() => {
        const selectedFiles = this.selectedFilePaths();
        const selectedFolders = this.selectedFolderPaths();
        const all = this.allNodes();

        let totalBytes = 0;
        for (const n of all) {
            if (n.type !== 'file' || n.size == null) continue;
            if (selectedFiles.has(n.path) || this.isCoveredByFolders(n.path, selectedFolders)) {
                totalBytes += n.size;
            }
        }
        return totalBytes;
    });

    ngOnInit(): void {
        this.loadAttachedFiles(() => {
            const folders = new Set(this.attachedFolderPaths());
            this.selectedFolderPaths.set(folders);
            this.selectedFilePaths.set(this.filesNotCoveredByFolders(this.attachedFilePaths(), folders));
            this.loadTree(() => this.expandToAttachedPaths());
        });
    }

    toggleExpand(event: Event, node: TreeNode): void {
        event.stopPropagation();
        node.isExpanded = !node.isExpanded;
        this.rootNodes.update((n) => [...n]);
        this.rebuildAllNodes();
    }

    toggleCheck(node: TreeNode): void {
        if (node.type === 'file') {
            const wasChecked = this.isChecked(node);
            if (wasChecked) {
                this.explodeCoveringFolders(node.path);
                this.selectedFilePaths.update((set) => {
                    const next = new Set(set);
                    next.delete(node.path);
                    return next;
                });
            } else {
                this.selectedFilePaths.update((set) => {
                    const next = new Set(set);
                    next.add(node.path);
                    return next;
                });
            }
            return;
        }

        const checked = this.isChecked(node);
        if (checked) {
            if (
                !this.selectedFolderPaths().has(node.path) &&
                this.isCoveredByFolders(node.path, this.selectedFolderPaths())
            ) {
                this.explodeCoveringFolders(node.path, node.path);
                return;
            }

            this.selectedFolderPaths.update((set) => {
                const next = new Set(set);
                next.delete(node.path);
                for (const f of set) {
                    if (f.startsWith(`${node.path}/`)) next.delete(f);
                }
                return next;
            });
            this.removeDescendantFileSelections(node);
            this.clearAncestorFolders(node.path);
            return;
        }

        this.selectedFolderPaths.update((set) => {
            const next = new Set(set);
            next.add(node.path);
            for (const f of set) {
                if (f.startsWith(`${node.path}/`)) next.delete(f);
            }
            return next;
        });
        this.removeDescendantFileSelections(node);
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

    private isCoveredByFolders(path: string, folders: Set<string>): boolean {
        for (const folder of folders) {
            if (path === folder || path.startsWith(`${folder}/`)) return true;
        }
        return false;
    }

    private filesNotCoveredByFolders(files: Set<string>, folders: Set<string>): Set<string> {
        if (folders.size === 0) return new Set(files);
        const next = new Set<string>();
        for (const p of files) {
            if (!this.isCoveredByFolders(p, folders)) next.add(p);
        }
        return next;
    }

    private isFileEffectivelySelected(path: string): boolean {
        return this.selectedFilePaths().has(path) || this.isCoveredByFolders(path, this.selectedFolderPaths());
    }

    private removeDescendantFileSelections(node: TreeNode): void {
        const descendants = this.collectFilePaths(node);
        if (descendants.length === 0) return;
        this.selectedFilePaths.update((set) => {
            let changed = false;
            const next = new Set(set);
            for (const p of descendants) {
                if (next.delete(p)) changed = true;
            }
            return changed ? next : set;
        });
    }

    /** Convert covering folder selections into explicit file selections, excluding `path` (and optional folder subtree). */
    private explodeCoveringFolders(path: string, excludeFolderPath?: string): void {
        const folders = this.selectedFolderPaths();
        const covering = [...folders].filter((f) => path === f || path.startsWith(`${f}/`));
        if (covering.length === 0) return;

        const keepFiles = new Set<string>();
        for (const folderPath of covering) {
            const folderNode = this.findNodeByPath(this.rootNodes(), folderPath);
            if (!folderNode) continue;
            for (const fp of this.collectFilePaths(folderNode)) {
                if (fp === path) continue;
                if (excludeFolderPath && (fp === excludeFolderPath || fp.startsWith(`${excludeFolderPath}/`))) {
                    continue;
                }
                keepFiles.add(fp);
            }
        }

        this.selectedFolderPaths.update((set) => {
            const next = new Set(set);
            for (const f of covering) next.delete(f);
            if (excludeFolderPath) {
                next.delete(excludeFolderPath);
                for (const f of set) {
                    if (f.startsWith(`${excludeFolderPath}/`)) next.delete(f);
                }
            }
            return next;
        });

        this.selectedFilePaths.update((set) => {
            const next = new Set(set);
            for (const fp of keepFiles) next.add(fp);
            next.delete(path);
            if (excludeFolderPath) {
                for (const fp of [...next]) {
                    if (fp === excludeFolderPath || fp.startsWith(`${excludeFolderPath}/`)) next.delete(fp);
                }
            }
            return next;
        });
    }

    isChecked(node: TreeNode): boolean {
        if (node.type === 'file') return this.isFileEffectivelySelected(node.path);
        if (this.selectedFolderPaths().has(node.path)) return true;
        if (this.isCoveredByFolders(node.path, this.selectedFolderPaths())) return true;
        const files = this.collectFilePaths(node);
        if (files.length === 0) return false;
        return files.every((p) => this.isFileEffectivelySelected(p));
    }

    isIndeterminate(node: TreeNode): boolean {
        if (node.type !== 'folder') return false;
        if (this.selectedFolderPaths().has(node.path)) return false;
        if (this.isCoveredByFolders(node.path, this.selectedFolderPaths())) return false;
        const files = this.collectFilePaths(node);
        if (files.length === 0) return false;
        const matched = files.filter((p) => this.isFileEffectivelySelected(p)).length;
        return matched > 0 && matched < files.length;
    }

    onConfirm(): void {
        if (!this.hasChanges() || this.isSaving()) {
            this.dialogRef.close({ changed: this.hasMadeChanges });
            return;
        }

        const { checks, unchecks } = this.computeDiff();
        const selectedFolders = this.selectedFolderPaths();
        const intentionalUnchecks = unchecks.filter(
            (p) => p.endsWith('/') || !this.isCoveredByFolders(p, selectedFolders)
        );

        if (intentionalUnchecks.length > 0) {
            const flowName = this.escapeHtml(this.flowName);
            let title: string;
            let message: string;

            if (intentionalUnchecks.length === 1) {
                const fileName = this.escapeHtml(this.getFileName(intentionalUnchecks[0]));
                title = 'Remove File?';
                message = `Are you sure you want to remove <strong>${fileName}</strong> file from the <strong>${flowName}</strong> flow?`;
            } else {
                title = 'Remove Files?';
                message = `Are you sure you want to remove <strong>${intentionalUnchecks.length} files</strong> from the <strong>${flowName}</strong> flow?`;
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

        const selectedFolders = this.selectedFolderPaths();
        const attachedFolders = this.attachedFolderPaths();
        for (const p of selectedFolders) if (!attachedFolders.has(p)) checks.push(`${p}/`);
        for (const p of attachedFolders) if (!selectedFolders.has(p)) unchecks.push(`${p}/`);

        const selectedFiles = this.filesNotCoveredByFolders(this.selectedFilePaths(), selectedFolders);
        const attachedFiles = this.attachedFilePaths();

        for (const p of selectedFiles) {
            if (!attachedFiles.has(p)) checks.push(p);
        }
        for (const p of attachedFiles) {
            if (this.isCoveredByFolders(p, selectedFolders)) {
                unchecks.push(p);
                continue;
            }
            if (!selectedFiles.has(p)) unchecks.push(p);
        }

        // BE remove_from_graph matches {p, p.rstrip('/'), p+'/'} — never remove a path
        // that is also being added in the same save (forkJoin race).
        const checkKeys = new Set(checks.map((p) => p.replace(/\/+$/, '')));
        return {
            checks,
            unchecks: unchecks.filter((p) => !checkKeys.has(p.replace(/\/+$/, ''))),
        };
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

    onFilesDropped(dropped: FileList): void {
        if (this.isUploading() || dropped.length === 0) return;
        const files = Array.from(dropped);

        this.isUploading.set(true);
        this.storageApiService
            .confirmOverwrite('', files)
            .pipe(
                switchMap((confirmed) => {
                    if (!confirmed) return EMPTY;
                    return this.storageApiService.handleAddFilesResult({
                        targetPath: '',
                        files,
                        mkdirOnly: false,
                    });
                }),
                takeUntilDestroyed(this.destroyRef)
            )
            .subscribe({
                next: (res) => {
                    if (res?.type === 'upload') {
                        this.toastService.success(
                            res.count === 1 ? 'File uploaded successfully' : `${res.count} files uploaded successfully`
                        );
                    }
                    this.reloadTree();
                },
                error: () => {
                    this.toastService.error('Failed to upload files');
                    this.isUploading.set(false);
                },
                complete: () => this.isUploading.set(false),
            });
    }

    private reloadTree(): void {
        this.rootNodes.set([]);
        this.allNodes.set([]);
        this.isLoadingRoot.set(true);
        this.loadTree(() => this.expandToAttachedPaths());
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

    /** Load the entire storage tree in a single request and build the node tree. */
    private loadTree(onDone?: () => void): void {
        this.isLoadingRoot.set(true);
        this.storageApiService
            .tree()
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe({
                next: (res) => {
                    const roots = (res.tree.children ?? []).map((n) => this.mapTreeNode(n, 0));
                    this.rootNodes.set(roots);
                    this.isLoadingRoot.set(false);
                    this.rebuildAllNodes();
                    if (res.truncated) {
                        this.toastService.error(
                            'Storage tree is too large to display fully. Some files may not be shown.'
                        );
                    }
                    onDone?.();
                },
                error: () => {
                    this.rootNodes.set([]);
                    this.isLoadingRoot.set(false);
                    this.rebuildAllNodes();
                    onDone?.();
                },
            });
    }

    private mapTreeNode(node: StorageTreeNode, level: number): TreeNode {
        const children = (node.children ?? []).map((c) => this.mapTreeNode(c, level + 1));
        return {
            name: node.name,
            path: node.path,
            type: node.type,
            level,
            isExpanded: false,
            hasChildren: node.type === 'folder' && children.length > 0,
            children,
            size: node.size,
        };
    }

    private expandToAttachedPaths(): void {
        const ancestorPaths = new Set<string>();
        for (const file of this.attachedFiles()) {
            const parts = file.path.split('/').filter(Boolean);
            for (let i = 1; i < parts.length; i++) {
                ancestorPaths.add(parts.slice(0, i).join('/'));
            }
        }

        for (const path of ancestorPaths) {
            const node = this.findNodeByPath(this.rootNodes(), path);
            if (node && node.type === 'folder') node.isExpanded = true;
        }

        this.rootNodes.update((n) => [...n]);
        this.rebuildAllNodes();
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
