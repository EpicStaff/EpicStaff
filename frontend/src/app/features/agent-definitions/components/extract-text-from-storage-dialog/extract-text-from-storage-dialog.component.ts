import { DialogRef } from '@angular/cdk/dialog';
import { ChangeDetectionStrategy, Component, computed, DestroyRef, inject, OnInit, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { FormsModule } from '@angular/forms';

import { AppSvgIconComponent } from '../../../../shared/components/app-svg-icon/app-svg-icon.component';
import { StorageItem } from '../../../files/models/storage.models';
import { StorageApiService } from '../../../files/services/storage-api.service';
import { getFileExtension } from '../../../files/utils/storage-file.utils';
import { isInstructionsTextFile } from '../../utils/instructions-file.utils';

export interface ExtractTextFromStorageDialogResult {
    item: StorageItem;
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
}

/**
 * Read-only, single-select storage file picker used to pull instruction text
 * out of storage. Lists only folders and text-like files (see
 * {@link isInstructionsTextFile}); picking a file closes the dialog with the
 * chosen {@link StorageItem}. It intentionally has no context menu / rename /
 * delete / drag-drop — those belong to the full explorer tree, not a picker.
 */
@Component({
    selector: 'app-extract-text-from-storage-dialog',
    imports: [FormsModule, AppSvgIconComponent],
    templateUrl: './extract-text-from-storage-dialog.component.html',
    styleUrls: ['./extract-text-from-storage-dialog.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class ExtractTextFromStorageDialogComponent implements OnInit {
    private readonly dialogRef = inject<DialogRef<ExtractTextFromStorageDialogResult | undefined>>(DialogRef);
    private readonly storageApiService = inject(StorageApiService);
    private readonly destroyRef = inject(DestroyRef);

    readonly searchQuery = signal('');
    readonly rootNodes = signal<TreeNode[]>([]);
    readonly isLoadingRoot = signal(true);

    private readonly allNodes = signal<TreeNode[]>([]);

    readonly visibleNodes = computed<TreeNode[]>(() => {
        const query = this.searchQuery().toLowerCase().trim();
        if (query) {
            // Flatten matches to level 0 — their ancestors aren't shown, so any
            // indentation would imply a nesting that isn't visible.
            return this.allNodes()
                .filter((n) => n.name.toLowerCase().includes(query))
                .map((n) => ({ ...n, level: 0 }));
        }
        return this.buildVisible(this.rootNodes());
    });

    ngOnInit(): void {
        this.loadLevel('', null);
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

    onNodeClick(node: TreeNode): void {
        if (node.type === 'folder') {
            this.toggleExpand(new Event('click'), node);
            return;
        }
        this.dialogRef.close({ item: this.toStorageItem(node) });
    }

    onCancel(): void {
        this.dialogRef.close(undefined);
    }

    getFileIcon(node: TreeNode): string {
        if (node.type === 'folder') return 'folder-storage';
        const ext = getFileExtension(node.name);
        if (ext === 'txt') return 'file-txt';
        if (ext === 'json') return 'file-json';
        return 'file';
    }

    private toStorageItem(node: TreeNode): StorageItem {
        return { name: node.name, path: node.path, type: node.type };
    }

    private loadLevel(path: string, parent: TreeNode | null): void {
        this.storageApiService
            .list(path)
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe({
                next: (items) => {
                    const nodes: TreeNode[] = items
                        // Only folders and valid text files are pickable here.
                        .filter((i) => i.type === 'folder' || isInstructionsTextFile(i.name))
                        .map((i) => ({
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

    private buildVisible(nodes: TreeNode[]): TreeNode[] {
        const flat: TreeNode[] = [];
        const walk = (list: TreeNode[]): void => {
            for (const n of list) {
                flat.push(n);
                if (n.type === 'folder' && n.isExpanded && n.children.length) walk(n.children);
            }
        };
        walk(nodes);
        return flat;
    }

    private rebuildAllNodes(): void {
        const flat: TreeNode[] = [];
        const walk = (list: TreeNode[]): void => {
            for (const n of list) {
                flat.push(n);
                if (n.children.length) walk(n.children);
            }
        };
        walk(this.rootNodes());
        this.allNodes.set(flat);
    }
}
