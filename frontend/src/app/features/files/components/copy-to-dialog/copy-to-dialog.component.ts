import { DIALOG_DATA, DialogRef } from '@angular/cdk/dialog';
import {
    ChangeDetectionStrategy,
    Component,
    computed,
    DestroyRef,
    ElementRef,
    HostListener,
    inject,
    signal,
    ViewChild,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { FormsModule } from '@angular/forms';

import { AppSvgIconComponent } from '../../../../shared/components/app-svg-icon/app-svg-icon.component';
import { StorageItem } from '../../models/storage.models';
import { StorageApiService } from '../../services/storage-api.service';

export interface CopyToDialogData {
    item: StorageItem;
}

export interface CopyToDialogResult {
    toPath: string;
}

export interface FolderNode {
    name: string;
    path: string;
    level: number;
    isExpanded: boolean;
    isLoading: boolean;
    hasChildren: boolean;
    children: FolderNode[];
    isLoaded: boolean;
}

@Component({
    selector: 'app-copy-to-dialog',
    imports: [FormsModule, AppSvgIconComponent],
    templateUrl: './copy-to-dialog.component.html',
    styleUrls: ['./copy-to-dialog.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class CopyToDialogComponent {
    private dialogRef = inject(DialogRef<CopyToDialogResult>);
    readonly data: CopyToDialogData = inject(DIALOG_DATA);
    private storageApiService = inject(StorageApiService);
    private destroyRef = inject(DestroyRef);

    @ViewChild('selectorEl') selectorElRef?: ElementRef<HTMLElement>;

    readonly searchQuery = signal('');
    readonly selectedPath = signal<string | null>(null);
    readonly rootNodes = signal<FolderNode[]>([]);
    readonly isLoadingRoot = signal(true);
    readonly dropdownOpen = signal(false);
    readonly dropdownMaxHeight = signal(400);

    private readonly allNodes = signal<FolderNode[]>([]);

    readonly visibleNodes = computed(() => {
        const query = this.searchQuery().toLowerCase().trim();
        const roots = this.rootNodes();
        if (query) {
            return this.allNodes().filter((n) => n.name.toLowerCase().includes(query));
        }
        return this.buildVisible(roots);
    });

    get selectedFolderLabel(): string {
        const path = this.selectedPath();
        if (path === null) return '';
        return path ? `/${path}` : '/';
    }

    get isValid(): boolean {
        return this.selectedPath() !== null;
    }

    ngOnInit(): void {
        this.loadLevel('', null);
    }

    @HostListener('document:click')
    onDocumentClick(): void {
        this.dropdownOpen.set(false);
    }

    toggleDropdown(event: MouseEvent): void {
        event.stopPropagation();
        const opening = !this.dropdownOpen();
        if (opening && this.selectorElRef) {
            const rect = this.selectorElRef.nativeElement.getBoundingClientRect();
            this.dropdownMaxHeight.set(Math.max(120, window.innerHeight - rect.bottom - 12));
        }
        this.dropdownOpen.update((v) => !v);
    }

    stopPropagation(event: MouseEvent): void {
        event.stopPropagation();
    }

    toggleExpand(event: Event, node: FolderNode): void {
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
    }

    selectFolder(path: string): void {
        this.selectedPath.set(path);
        this.dropdownOpen.set(false);
    }

    isSelected(path: string): boolean {
        return this.selectedPath() === path;
    }

    onConfirm(): void {
        if (!this.isValid) return;
        this.dialogRef.close({ toPath: this.selectedPath()! });
    }

    onCancel(): void {
        this.dialogRef.close();
    }

    private loadLevel(path: string, parent: FolderNode | null): void {
        this.storageApiService
            .list(path)
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe({
                next: (items) => {
                    const folders = items
                        .filter((i) => i.type === 'folder')
                        .map(
                            (i): FolderNode => ({
                                name: i.name,
                                path: this.resolveFolderPath(path, i.name, i.path),
                                level: parent ? parent.level + 1 : 0,
                                isExpanded: false,
                                isLoading: false,
                                hasChildren: !i.is_empty,
                                children: [],
                                isLoaded: false,
                            })
                        );

                    if (parent) {
                        parent.children = folders;
                        parent.isLoaded = true;
                        parent.isLoading = false;
                        parent.hasChildren = folders.length > 0;
                        if (folders.length === 0) {
                            parent.isExpanded = false;
                        }
                    } else {
                        this.rootNodes.set(folders);
                        this.isLoadingRoot.set(false);
                    }

                    this.rebuildAllNodes();
                    this.rootNodes.update((n) => [...n]);
                },
                error: () => {
                    if (parent) {
                        parent.isLoading = false;
                        parent.isLoaded = true;
                    } else {
                        this.isLoadingRoot.set(false);
                    }
                    this.rootNodes.update((n) => [...n]);
                },
            });
    }

    private buildVisible(nodes: FolderNode[]): FolderNode[] {
        const result: FolderNode[] = [];
        for (const node of nodes) {
            result.push(node);
            if (node.isExpanded && node.children.length > 0) {
                result.push(...this.buildVisible(node.children));
            }
        }
        return result;
    }

    private resolveFolderPath(parentPath: string, name: string, providedPath?: string): string {
        if (providedPath?.trim()) {
            return this.normalizeStoragePath(providedPath);
        }
        const normalizedParent = this.normalizeStoragePath(parentPath);
        const normalizedName = this.normalizeStoragePath(name);
        return normalizedParent ? `${normalizedParent}/${normalizedName}` : normalizedName;
    }

    private normalizeStoragePath(path: string): string {
        return path
            .trim()
            .replace(/\\/g, '/')
            .replace(/\/{2,}/g, '/')
            .replace(/^\/+|\/+$/g, '');
    }

    private rebuildAllNodes(): void {
        this.allNodes.set(this.buildVisible(this.rootNodes()));
    }
}
