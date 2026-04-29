import { Dialog } from '@angular/cdk/dialog';
import {
    ChangeDetectionStrategy,
    Component,
    computed,
    DestroyRef,
    HostListener,
    inject,
    input,
    OnInit,
    signal,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { FormsModule } from '@angular/forms';
import { forkJoin } from 'rxjs';

import {
    CreateFolderDialogComponent,
    CreateFolderDialogResult,
} from '../../../features/files/components/create-folder-dialog/create-folder-dialog.component';
import { GraphFileRecord } from '../../../features/files/models/storage.models';
import { StorageApiService } from '../../../features/files/services/storage-api.service';
import { getFileExtension } from '../../../features/files/utils/storage-file.utils';
import { ToastService } from '../../../services/notifications/toast.service';
import { AppSvgIconComponent } from '../../../shared/components/app-svg-icon/app-svg-icon.component';
import { ConfirmationDialogService } from '../../../shared/components/cofirm-dialog';

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
}

@Component({
    selector: 'app-flow-files-button',
    imports: [FormsModule, AppSvgIconComponent],
    templateUrl: './flow-files-button.component.html',
    styleUrls: ['./flow-files-button.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class FlowFilesButtonComponent implements OnInit {
    readonly flowId = input.required<number>();
    readonly flowName = input.required<string>();

    private storageApiService = inject(StorageApiService);
    private confirmationDialogService = inject(ConfirmationDialogService);
    private dialog = inject(Dialog);
    private toastService = inject(ToastService);
    private destroyRef = inject(DestroyRef);

    readonly attachedFiles = signal<GraphFileRecord[]>([]);
    readonly attachedPaths = computed(() => new Set(this.attachedFiles().map((f) => f.path.replace(/\/+$/, ''))));
    readonly dropdownOpen = signal(false);
    readonly searchQuery = signal('');
    readonly rootNodes = signal<TreeNode[]>([]);
    readonly isLoadingRoot = signal(true);
    readonly isSaving = signal(false);
    readonly pendingChecks = signal<Set<string>>(new Set());
    readonly pendingUnchecks = signal<Set<string>>(new Set());
    private treeLoaded = false;
    private dialogOpen = false;

    readonly attachedCount = computed(() => {
        const attached = this.attachedPaths();
        const checks = this.pendingChecks();
        const unchecks = this.pendingUnchecks();
        let count = 0;
        for (const p of attached) {
            if (!unchecks.has(p)) count++;
        }
        for (const p of checks) {
            if (!attached.has(p)) count++;
        }
        return count;
    });

    readonly hasChanges = computed(() => this.pendingChecks().size > 0 || this.pendingUnchecks().size > 0);

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

    ngOnInit(): void {
        this.loadAttachedFiles();
    }

    @HostListener('document:click')
    onDocumentClick(): void {
        if (this.dialogOpen) return;
        if (this.dropdownOpen()) {
            this.resetPending();
            this.dropdownOpen.set(false);
        }
    }

    toggleDropdown(event: MouseEvent): void {
        event.stopPropagation();
        const opening = !this.dropdownOpen();
        this.dropdownOpen.set(opening);
        if (opening && !this.treeLoaded) {
            this.loadLevel('', null, () => this.expandToAttachedPaths());
            this.treeLoaded = true;
        }
        if (!opening) {
            this.resetPending();
        }
    }

    stopPropagation(event: MouseEvent): void {
        event.stopPropagation();
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
        const path = node.path;
        const isCurrentlyChecked = this.isChecked(node);

        if (isCurrentlyChecked) {
            // Unchecking
            if (this.pendingChecks().has(path)) {
                this.pendingChecks.update((set) => {
                    const next = new Set(set);
                    next.delete(path);
                    return next;
                });
            } else if (this.attachedPaths().has(path)) {
                this.pendingUnchecks.update((set) => {
                    const next = new Set(set);
                    next.add(path);
                    return next;
                });
            }
        } else {
            // Checking
            if (this.pendingUnchecks().has(path)) {
                this.pendingUnchecks.update((set) => {
                    const next = new Set(set);
                    next.delete(path);
                    return next;
                });
            } else {
                this.pendingChecks.update((set) => {
                    const next = new Set(set);
                    next.add(path);
                    return next;
                });
            }
        }
    }

    isChecked(node: TreeNode): boolean {
        const path = node.path;
        if (this.pendingUnchecks().has(path)) return false;
        if (this.pendingChecks().has(path)) return true;
        return this.attachedPaths().has(path);
    }

    onSave(): void {
        if (!this.hasChanges() || this.isSaving()) return;

        const unchecks = Array.from(this.pendingUnchecks());

        if (unchecks.length > 0) {
            const flowName = this.escapeHtml(this.flowName());
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

            this.dialogOpen = true;
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
                    setTimeout(() => (this.dialogOpen = false));
                    if (confirmed === true) {
                        this.executeSave();
                    }
                });
        } else {
            this.executeSave();
        }
    }

    private executeSave(): void {
        this.isSaving.set(true);
        const flowId = this.flowId();
        const checks = Array.from(this.pendingChecks());
        const unchecks = Array.from(this.pendingUnchecks());

        const requests = [
            ...(checks.length ? [this.storageApiService.addToGraph(checks, [flowId])] : []),
            ...(unchecks.length ? [this.storageApiService.removeFromGraph(unchecks, [flowId])] : []),
        ];

        if (requests.length === 0) {
            this.isSaving.set(false);
            return;
        }

        forkJoin(requests)
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe({
                next: () => {
                    this.isSaving.set(false);
                    this.resetPending();
                    this.loadAttachedFiles();
                    this.dropdownOpen.set(false);
                    this.toastService.success('Files updated successfully');
                },
                error: () => {
                    this.isSaving.set(false);
                    this.toastService.error('Failed to update files');
                },
            });
    }

    private getFileName(path: string): string {
        const parts = path.replace(/\/+$/, '').split('/');
        return parts[parts.length - 1] || path;
    }

    onCancel(): void {
        this.resetPending();
        this.dropdownOpen.set(false);
    }

    onClear(): void {
        const attached = this.attachedPaths();
        if (attached.size === 0 && this.pendingChecks().size === 0) return;

        this.pendingChecks.set(new Set());
        this.pendingUnchecks.set(new Set(attached));
    }

    onUploadNew(): void {
        this.dialogOpen = true;
        const dialogRef = this.dialog.open<CreateFolderDialogResult>(CreateFolderDialogComponent, {
            data: {},
        });

        dialogRef.closed.pipe(takeUntilDestroyed(this.destroyRef)).subscribe((result) => {
            setTimeout(() => (this.dialogOpen = false));
            if (!result) return;
            // Refresh the tree after upload
            this.treeLoaded = false;
            this.rootNodes.set([]);
            this.isLoadingRoot.set(true);
            this.loadLevel('', null);
            this.treeLoaded = true;
        });
    }

    getFileIcon(node: TreeNode): string {
        if (node.type === 'folder') {
            return 'folder-storage';
        }
        const ext = getFileExtension(node.name);
        if (ext === 'txt') return 'file-txt';
        if (ext === 'pdf') return 'file-pdf';
        if (ext === 'docx') return 'file-docx';
        if (ext === 'json') return 'file-json';
        if (ext === 'html') return 'file-html';
        return 'file';
    }

    private loadAttachedFiles(): void {
        this.storageApiService
            .getGraphFiles(this.flowId())
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe({
                next: (files) => this.attachedFiles.set(files),
                error: () => this.attachedFiles.set([]),
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

    private expandToAttachedPaths(): void {
        const ancestorPaths = new Set<string>();
        for (const file of this.attachedFiles()) {
            const parts = file.path.split('/').filter(Boolean);
            for (let i = 1; i < parts.length; i++) {
                ancestorPaths.add(parts.slice(0, i).join('/'));
            }
        }

        const findNode = (nodes: TreeNode[], path: string): TreeNode | null => {
            for (const n of nodes) {
                if (n.path === path) return n;
                if (n.children.length > 0) {
                    const found = findNode(n.children, path);
                    if (found) return found;
                }
            }
            return null;
        };

        const tryExpand = (): void => {
            for (const path of ancestorPaths) {
                const node = findNode(this.rootNodes(), path);
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

    private resetPending(): void {
        this.pendingChecks.set(new Set());
        this.pendingUnchecks.set(new Set());
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
