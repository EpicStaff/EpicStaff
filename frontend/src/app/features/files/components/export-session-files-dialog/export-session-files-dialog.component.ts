import { DIALOG_DATA, DialogRef } from '@angular/cdk/dialog';
import { ChangeDetectionStrategy, Component, computed, DestroyRef, inject, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { FormsModule } from '@angular/forms';
import { Router } from '@angular/router';

import { ToastService } from '../../../../services/notifications/toast.service';
import { AppSvgIconComponent } from '../../../../shared/components/app-svg-icon/app-svg-icon.component';
import { Spinner2Component } from '../../../../shared/components/spinner-type2/spinner.component';
import { SessionOutputFile } from '../../models/storage.models';
import { StorageApiService } from '../../services/storage-api.service';
import { getFileExtension } from '../../utils/storage-file.utils';

export interface ExportSessionFilesDialogData {
    sessionId: string;
    outputFiles: SessionOutputFile[];
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
    selector: 'app-export-session-files-dialog',
    imports: [FormsModule, AppSvgIconComponent, Spinner2Component],
    templateUrl: './export-session-files-dialog.component.html',
    styleUrls: ['./export-session-files-dialog.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class ExportSessionFilesDialogComponent {
    private readonly dialogRef = inject<DialogRef<void>>(DialogRef);
    private readonly data: ExportSessionFilesDialogData = inject(DIALOG_DATA);
    private readonly storageApiService = inject(StorageApiService);
    private readonly toastService = inject(ToastService);
    private readonly router = inject(Router);
    private readonly destroyRef = inject(DestroyRef);

    readonly outputFiles = signal<SessionOutputFile[]>(this.data.outputFiles);
    readonly rootNodes = signal<TreeNode[]>([]);
    readonly searchQuery = signal('');
    readonly selected = signal<Set<string>>(new Set());
    readonly isDownloading = signal(false);

    readonly allFilePaths = computed(() => this.outputFiles().map((f) => f.path));
    readonly hasSelection = computed(() => this.selected().size > 0);

    readonly selectedCount = computed(() => this.selected().size);

    private readonly flatNodes = computed(() => this.flatten(this.rootNodes()));

    readonly visibleNodes = computed(() => {
        const query = this.searchQuery().toLowerCase().trim();
        if (query) {
            const filtered = this.flatNodes().filter((n) => n.name.toLowerCase().includes(query));
            const minLevel = filtered.reduce((min, n) => Math.min(min, n.level), Infinity);
            return filtered.map((n) => ({ ...n, level: n.level - minLevel }));
        }
        return this.buildVisible(this.rootNodes());
    });

    ngOnInit(): void {
        this.rootNodes.set(this.buildTreeFromPaths(this.outputFiles()));
    }

    toggleExpand(event: Event, node: TreeNode): void {
        event.stopPropagation();
        node.isExpanded = !node.isExpanded;
        this.rootNodes.update((n) => [...n]);
    }

    toggleCheck(node: TreeNode): void {
        const descendantFilePaths = this.collectFilePaths(node);
        const current = new Set(this.selected());
        const allChecked = descendantFilePaths.every((p) => current.has(p));
        if (allChecked) {
            for (const p of descendantFilePaths) current.delete(p);
        } else {
            for (const p of descendantFilePaths) current.add(p);
        }
        this.selected.set(current);
    }

    isChecked(node: TreeNode): boolean {
        const descendantFilePaths = this.collectFilePaths(node);
        if (descendantFilePaths.length === 0) return false;
        const selected = this.selected();
        return descendantFilePaths.every((p) => selected.has(p));
    }

    isIndeterminate(node: TreeNode): boolean {
        if (node.type !== 'folder') return false;
        const descendantFilePaths = this.collectFilePaths(node);
        if (descendantFilePaths.length === 0) return false;
        const selected = this.selected();
        const matched = descendantFilePaths.filter((p) => selected.has(p)).length;
        return matched > 0 && matched < descendantFilePaths.length;
    }

    onConfirm(): void {
        if (this.isDownloading()) return;

        const selected = Array.from(this.selected());
        const paths = selected.length > 0 ? selected : this.allFilePaths();
        if (paths.length === 0) {
            this.dialogRef.close();
            return;
        }
        if (paths.length === 1) {
            //TODO check downloading bug
            this.storageApiService.download(paths[0]);
            this.dialogRef.close();
            return;
        }
        this.downloadPathsAsZip(paths, 'session-outputs.zip');
    }

    onCancel(): void {
        this.dialogRef.close();
    }

    onDeepLink(event: Event, node: TreeNode): void {
        event.stopPropagation();
        this.dialogRef.close();
        this.router.navigate(['/files/storage'], { queryParams: { path: node.path } });
    }

    formatSize(bytes: number): string {
        if (bytes < 1024) return `${bytes} B`;
        if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
        return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
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

    private downloadPathsAsZip(paths: string[], filename: string): void {
        this.isDownloading.set(true);
        this.storageApiService
            .downloadZip(paths)
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe({
                next: (blob) => {
                    const url = URL.createObjectURL(blob);
                    const a = document.createElement('a');
                    a.href = url;
                    a.download = filename;
                    a.click();
                    URL.revokeObjectURL(url);
                    this.isDownloading.set(false);
                    this.dialogRef.close();
                },
                error: () => {
                    this.toastService.error('Failed to download files');
                    this.isDownloading.set(false);
                },
            });
    }

    private buildTreeFromPaths(files: SessionOutputFile[]): TreeNode[] {
        const root: TreeNode[] = [];
        const folderMap = new Map<string, TreeNode>();

        for (const file of files) {
            const parts = file.path.split('/').filter(Boolean);
            if (parts.length === 0) continue;

            let parentChildren = root;
            let currentPath = '';
            for (let i = 0; i < parts.length - 1; i++) {
                currentPath = currentPath ? `${currentPath}/${parts[i]}` : parts[i];
                let folder = folderMap.get(currentPath);
                if (!folder) {
                    folder = {
                        name: parts[i],
                        path: currentPath,
                        type: 'folder',
                        level: i,
                        isExpanded: true,
                        hasChildren: true,
                        children: [],
                    };
                    folderMap.set(currentPath, folder);
                    parentChildren.push(folder);
                }
                parentChildren = folder.children;
            }

            const leafName = parts[parts.length - 1];
            parentChildren.push({
                name: file.name || leafName,
                path: file.path,
                type: 'file',
                level: parts.length - 1,
                isExpanded: false,
                hasChildren: false,
                children: [],
                size: file.size,
            });
        }

        return root;
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

    private flatten(nodes: TreeNode[]): TreeNode[] {
        const result: TreeNode[] = [];
        for (const node of nodes) {
            result.push(node);
            if (node.children.length > 0) {
                result.push(...this.flatten(node.children));
            }
        }
        return result;
    }
}
