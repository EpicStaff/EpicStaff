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
import { MatTooltipModule } from '@angular/material/tooltip';
import { AppSvgIconComponent } from '@shared/components';

import { StorageItem } from '../../models/storage.models';
import { StorageApiService } from '../../services/storage-api.service';
import { flattenFolderNodes, StorageFolderNode, toFolderNodes } from '../../utils/storage-tree.utils';

export interface CopyToDialogData {
    item: StorageItem;
}

export interface CopyToDialogResult {
    toPath: string;
}

@Component({
    selector: 'app-copy-to-dialog',
    imports: [FormsModule, AppSvgIconComponent, MatTooltipModule],
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
    readonly rootNodes = signal<StorageFolderNode[]>([]);
    readonly isLoadingRoot = signal(true);
    readonly dropdownOpen = signal(false);
    readonly dropdownMaxHeight = signal(400);

    private readonly allNodes = signal<StorageFolderNode[]>([]);

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
        this.loadFolderTree();
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

    toggleExpand(event: Event, node: StorageFolderNode): void {
        event.stopPropagation();
        node.isExpanded = !node.isExpanded;
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

    private loadFolderTree(): void {
        this.storageApiService
            .tree()
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe({
                next: (response) => {
                    const roots = toFolderNodes(response.tree.children);
                    this.rootNodes.set(roots);
                    this.allNodes.set(flattenFolderNodes(roots));
                    this.isLoadingRoot.set(false);
                },
                error: () => this.isLoadingRoot.set(false),
            });
    }

    private buildVisible(nodes: StorageFolderNode[]): StorageFolderNode[] {
        const result: StorageFolderNode[] = [];
        for (const node of nodes) {
            result.push(node);
            if (node.isExpanded && node.children.length > 0) {
                result.push(...this.buildVisible(node.children));
            }
        }
        return result;
    }
}
