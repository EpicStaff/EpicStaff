import {
    ChangeDetectionStrategy,
    Component,
    computed,
    DestroyRef,
    effect,
    ElementRef,
    HostListener,
    inject,
    input,
    OnInit,
    signal,
    ViewChild,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { FormsModule } from '@angular/forms';
import { Router } from '@angular/router';

import { SessionOutputFile } from '../../../../../features/files/models/storage.models';
import { StorageApiService } from '../../../../../features/files/services/storage-api.service';
import { getFileExtension } from '../../../../../features/files/utils/storage-file.utils';
import { GraphSessionStatus } from '../../../../../features/flows/services/flows-sessions.service';
import { ToastService } from '../../../../../services/notifications/toast.service';
import { AppSvgIconComponent } from '../../../../../shared/components/app-svg-icon/app-svg-icon.component';
import { CollapseOnOverflowDirective } from '../../../../../shared/directives/collapse-on-overflow.directive';

const TERMINAL_STATUSES = new Set([
    GraphSessionStatus.ENDED,
    GraphSessionStatus.ERROR,
    GraphSessionStatus.STOP,
    GraphSessionStatus.EXPIRED,
]);

interface TreeNode {
    name: string;
    path: string;
    type: 'file' | 'folder';
    level: number;
    isExpanded: boolean;
    hasChildren: boolean;
    children: TreeNode[];
}

@Component({
    selector: 'app-session-files-button',
    standalone: true,
    imports: [FormsModule, AppSvgIconComponent, CollapseOnOverflowDirective],
    templateUrl: './session-files-button.component.html',
    styleUrls: ['./session-files-button.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class SessionFilesButtonComponent implements OnInit {
    readonly sessionId = input.required<string>();
    readonly sessionStatus = input<GraphSessionStatus | null>(null);

    private readonly storageApiService = inject(StorageApiService);
    private readonly router = inject(Router);
    private readonly toastService = inject(ToastService);
    private readonly destroyRef = inject(DestroyRef);

    @ViewChild('btn', { static: false }) private readonly btnRef!: ElementRef<HTMLButtonElement>;

    readonly isLoaded = signal(false);
    readonly outputFiles = signal<SessionOutputFile[]>([]);
    readonly dropdownOpen = signal(false);
    readonly searchQuery = signal('');
    readonly rootNodes = signal<TreeNode[]>([]);
    readonly selected = signal<Set<string>>(new Set());
    readonly isDownloading = signal(false);
    readonly dropdownAlignRight = signal(false);

    readonly hasSelection = computed(() => this.selected().size > 0);

    readonly allFilePaths = computed(() => this.outputFiles().map((f) => f.path));

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

    constructor() {
        effect(() => {
            const status = this.sessionStatus();
            if (status && TERMINAL_STATUSES.has(status)) {
                this.loadFiles();
            }
        });
    }

    ngOnInit(): void {
        this.loadFiles();
    }

    private loadFiles(): void {
        this.storageApiService
            .getSessionOutputFiles(this.sessionId())
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe({
                next: (files) => {
                    this.outputFiles.set(files);
                    this.rootNodes.set(this.buildTreeFromPaths(files));
                    this.isLoaded.set(true);
                },
                error: () => {
                    this.outputFiles.set([]);
                    this.isLoaded.set(true);
                },
            });
    }

    @HostListener('document:click')
    onDocumentClick(): void {
        if (this.dropdownOpen()) {
            this.selected.set(new Set());
            this.dropdownOpen.set(false);
        }
    }

    toggleDropdown(event: MouseEvent): void {
        event.stopPropagation();
        const opening = !this.dropdownOpen();
        if (opening && this.btnRef) {
            const rect = this.btnRef.nativeElement.getBoundingClientRect();
            this.dropdownAlignRight.set(rect.left + 440 > window.innerWidth);
        }
        this.dropdownOpen.set(opening);
        if (!opening) {
            this.selected.set(new Set());
        }
    }

    stopPropagation(event: MouseEvent): void {
        event.stopPropagation();
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

    onDownloadAll(): void {
        const paths = this.allFilePaths();
        if (paths.length === 0) return;
        if (paths.length === 1) {
            this.storageApiService.download(paths[0]);
            return;
        }
        this.downloadPathsAsZip(paths, 'session-outputs.zip');
    }

    onDownloadSelected(): void {
        const paths = Array.from(this.selected());
        if (paths.length === 0) return;
        if (paths.length === 1) {
            this.storageApiService.download(paths[0]);
            return;
        }
        this.downloadPathsAsZip(paths, 'session-outputs.zip');
    }

    onCancel(): void {
        this.selected.set(new Set());
        this.dropdownOpen.set(false);
    }

    onDeepLink(event: Event, node: TreeNode): void {
        event.stopPropagation();
        this.dropdownOpen.set(false);
        this.router.navigate(['/files/storage'], { queryParams: { path: node.path } });
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
