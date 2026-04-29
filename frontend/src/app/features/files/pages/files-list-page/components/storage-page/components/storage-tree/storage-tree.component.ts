import { NgTemplateOutlet } from '@angular/common';
import { ChangeDetectionStrategy, Component, ElementRef, input, output, signal, ViewChild } from '@angular/core';

import { AppSvgIconComponent } from '../../../../../../../../shared/components/app-svg-icon/app-svg-icon.component';
import { StorageItem } from '../../../../../../models/storage.models';
import { getFileExtension } from '../../../../../../utils/storage-file.utils';

@Component({
    selector: 'app-storage-tree',
    imports: [NgTemplateOutlet, AppSvgIconComponent],
    templateUrl: './storage-tree.component.html',
    styleUrls: ['./storage-tree.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class StorageTreeComponent {
    items = input<StorageItem[]>([]);
    fileSelected = output<StorageItem>();
    folderSelected = output<StorageItem>();
    folderToggled = output<StorageItem>();
    contextAction = output<{
        action: string;
        item: StorageItem;
        selectedItems?: StorageItem[];
        renameFromPath?: string;
        targetPath?: string;
    }>();
    closeSidebar = output<void>();
    openCreateFolder = output<string>();
    selectionChange = output<StorageItem[]>();

    @ViewChild('renameInput') renameInputRef?: ElementRef<HTMLInputElement>;
    @ViewChild('listEl') listElRef?: ElementRef<HTMLElement>;

    private hoveredItemEl: HTMLElement | null = null;

    selectedItem = signal<StorageItem | null>(null);
    selectedPaths = signal<Set<string>>(new Set<string>());
    hoveredItem = signal<StorageItem | null>(null);
    renamingItem = signal<StorageItem | null>(null);
    renamePos = signal<{ top: number; left: number; right: number } | null>(null);
    renamingFromPath = '';
    renameValue = '';
    private selectionAnchorPath: string | null = null;

    contextMenuOpen = signal<boolean>(false);
    contextMenuPosition = signal<{ x: number; y: number }>({ x: 0, y: 0 });
    contextMenuItem = signal<StorageItem | null>(null);

    moreMenuOpen = signal<boolean>(false);
    moreMenuPosition = signal<{ x: number; y: number }>({ x: 0, y: 0 });

    // Drag-and-drop state
    draggedItem = signal<StorageItem | null>(null);
    dropTarget = signal<StorageItem | null>(null);
    dropTargetRoot = signal<boolean>(false);
    private dragExpandTimer: ReturnType<typeof setTimeout> | null = null;
    private readonly dragExpandDelay = 700;

    asStorageItems(nodes: StorageItem[] | null | undefined): StorageItem[] {
        return Array.isArray(nodes) ? nodes : [];
    }

    onItemClick(event: MouseEvent, item: StorageItem): void {
        this.updateSelection(event, item);
        this.selectedItem.set(item);
        const hasModifier = event.ctrlKey || event.metaKey || event.shiftKey;
        if (hasModifier) {
            return;
        }
        if (item.type === 'file') {
            this.fileSelected.emit(item);
        } else {
            this.folderSelected.emit(item);
        }
    }

    onFolderChevronClick(event: MouseEvent, item: StorageItem): void {
        event.preventDefault();
        event.stopPropagation();
        item.isExpanded = !item.isExpanded;
        this.folderToggled.emit(item);
    }

    onContextMenu(event: MouseEvent, item: StorageItem): void {
        event.preventDefault();
        event.stopPropagation();
        if (!this.isItemSelected(item)) {
            this.setSelectedPaths(new Set([item.path]));
            this.selectedItem.set(item);
            this.selectionAnchorPath = item.path;
        }
        this.contextMenuPosition.set(this.clampMenuPosition(event.clientX, event.clientY));
        this.contextMenuItem.set(item);
        this.contextMenuOpen.set(true);
    }

    onKebabClick(event: MouseEvent, item: StorageItem): void {
        event.stopPropagation();
        if (!this.isItemSelected(item)) {
            this.setSelectedPaths(new Set([item.path]));
            this.selectedItem.set(item);
            this.selectionAnchorPath = item.path;
        }
        this.contextMenuPosition.set(this.clampMenuPosition(event.clientX, event.clientY));
        this.contextMenuItem.set(item);
        this.contextMenuOpen.set(true);
    }

    private clampMenuPosition(x: number, y: number): { x: number; y: number } {
        const menuWidth = 170;
        const menuHeight = 200;
        return {
            x: Math.min(x, window.innerWidth - menuWidth - 8),
            y: Math.min(y, window.innerHeight - menuHeight - 8),
        };
    }

    closeContextMenu(): void {
        this.contextMenuOpen.set(false);
        this.contextMenuItem.set(null);
    }

    selectItemExternally(item: StorageItem): void {
        this.hoveredItemEl = null;
        this.setSelectedPaths(new Set([item.path]));
        this.selectedItem.set(item);
        this.selectionAnchorPath = item.path;
        setTimeout(() => this.scrollItemIntoView(item));
    }

    private scrollItemIntoView(item: StorageItem): void {
        const listEl = this.listElRef?.nativeElement;
        if (!listEl) return;
        const el = listEl.querySelector(`[data-path="${CSS.escape(item.path)}"]`) as HTMLElement | null;
        el?.scrollIntoView({ behavior: 'smooth', block: 'center' });
    }

    startRename(item: StorageItem): void {
        this.renamingFromPath = item.path || item.name;
        this.renameValue = item.name;

        const path = item.path || item.name;
        const itemEl =
            this.hoveredItemEl ??
            (this.listElRef?.nativeElement.querySelector(`[data-path="${CSS.escape(path)}"]`) as HTMLElement | null);
        const listEl = this.listElRef?.nativeElement;
        if (itemEl && listEl) {
            const itemRect = itemEl.getBoundingClientRect();
            const listRect = listEl.getBoundingClientRect();
            this.renamePos.set({
                top: itemRect.top,
                left: listRect.left,
                right: window.innerWidth - listRect.right,
            });
        } else {
            this.renamePos.set(null);
        }

        this.renamingItem.set(item);
        setTimeout(() => {
            this.renameInputRef?.nativeElement.focus();
            this.renameInputRef?.nativeElement.select();
        });
    }

    onContextMenuAction(action: string): void {
        const item = this.contextMenuItem();
        if (!item) return;

        if (action === 'rename') {
            this.startRename(item);
        } else if (action === 'delete') {
            const selectedSet = this.selectedPaths();
            const selectedItems = this.collectVisibleNodes(this.items()).filter((node) => selectedSet.has(node.path));
            if (selectedItems.length > 1) {
                this.contextAction.emit({ action: 'delete-selected', item, selectedItems });
            } else {
                this.contextAction.emit({ action, item });
            }
        } else {
            this.contextAction.emit({ action, item });
        }
        this.closeContextMenu();
    }

    onRenameConfirm(): void {
        const item = this.renamingItem();
        if (!item) {
            return;
        }
        this.renamingItem.set(null);
        this.renamePos.set(null);

        const newName = this.renameValue.trim();
        const currentPath = this.renamingFromPath;
        if (newName && newName !== item.name) {
            const slashIndex = currentPath.lastIndexOf('/');
            const parentPath = slashIndex >= 0 ? currentPath.substring(0, slashIndex) : '';
            const newPath = parentPath ? `${parentPath}/${newName}` : newName;
            this.contextAction.emit({
                action: 'rename',
                item: { ...item, name: newName, path: newPath },
                renameFromPath: currentPath,
            });
        }
    }

    onRenameCancel(event?: Event): void {
        event?.preventDefault();
        event?.stopPropagation();
        this.renamingItem.set(null);
        this.renamePos.set(null);
    }

    onRenameEnter(event: Event): void {
        event.preventDefault();
        event.stopPropagation();
        this.onRenameConfirm();
    }

    getFileIcon(item: StorageItem): string {
        if (item.type === 'folder') {
            return 'folder-storage';
        }
        const ext = getFileExtension(item.name);
        if (ext === 'txt') return 'file-txt';
        if (ext === 'pdf') return 'file-pdf';
        if (ext === 'docx') return 'file-docx';
        if (ext === 'json') return 'file-json';
        if (ext === 'html') return 'file-html';
        return 'file';
    }

    isItemSelected(item: StorageItem): boolean {
        return this.selectedPaths().has(item.path);
    }

    onAddFolderClick(): void {
        const selected = this.selectedItem();
        let currentFolder = '';
        if (selected?.path) {
            if (selected.type === 'folder') {
                currentFolder = selected.path;
            } else {
                const slashIndex = selected.path.lastIndexOf('/');
                currentFolder = slashIndex >= 0 ? selected.path.substring(0, slashIndex) : '';
            }
        }
        this.openCreateFolder.emit(currentFolder);
    }

    onItemMouseEnter(event: MouseEvent, node: StorageItem): void {
        this.hoveredItem.set(node);
        this.hoveredItemEl = event.currentTarget as HTMLElement;
    }

    onItemMouseLeave(): void {
        this.hoveredItem.set(null);
    }

    onAddFolderClickForNode(event: MouseEvent, node: StorageItem): void {
        event.stopPropagation();
        let currentFolder = '';
        if (node.type === 'folder') {
            currentFolder = node.path;
        } else {
            const slashIndex = node.path.lastIndexOf('/');
            currentFolder = slashIndex >= 0 ? node.path.substring(0, slashIndex) : '';
        }
        this.openCreateFolder.emit(currentFolder);
    }

    onMoreOptionsClick(event: MouseEvent): void {
        event.preventDefault();
        event.stopPropagation();
        const btn = event.currentTarget as HTMLElement;
        const rect = btn.getBoundingClientRect();
        const menuWidth = 180;
        const x = Math.min(rect.left, window.innerWidth - menuWidth - 8);
        const y = rect.bottom + 4;
        this.moreMenuPosition.set({ x, y });
        this.moreMenuOpen.set(true);
    }

    closeMoreMenu(): void {
        this.moreMenuOpen.set(false);
    }

    onMoreMenuAction(action: string): void {
        this.closeMoreMenu();
        const selectedSet = this.selectedPaths();
        const selectedItems = this.collectVisibleNodes(this.items()).filter((node) => selectedSet.has(node.path));
        if ((action === 'download-selected' || action === 'delete-selected') && selectedItems.length === 0) {
            return;
        }
        this.contextAction.emit({
            action,
            item: selectedItems[0] ?? this.selectedItem() ?? { name: '', path: '', type: 'folder' },
            selectedItems,
        });
    }

    // Drag-and-drop handlers
    onDragStart(event: DragEvent, item: StorageItem): void {
        if (this.renamingItem()) {
            event.preventDefault();
            return;
        }
        event.dataTransfer!.effectAllowed = 'move';
        event.dataTransfer!.setData('text/plain', item.path);
        this.draggedItem.set(item);
    }

    onDragOver(event: DragEvent, node: StorageItem): void {
        event.preventDefault();
        event.dataTransfer!.dropEffect = 'move';

        const dragged = this.draggedItem();
        if (!dragged) return;

        if (node.type !== 'folder' || !this.isValidDropTarget(dragged, node)) {
            if (this.dropTarget()?.path === node.path) {
                this.dropTarget.set(null);
            }
            return;
        }

        event.stopPropagation();
        this.dropTargetRoot.set(false);

        if (this.dropTarget()?.path !== node.path) {
            this.dropTarget.set(node);
            this.clearDragExpandTimer();
            if (node.type === 'folder' && !node.isExpanded) {
                this.dragExpandTimer = setTimeout(() => {
                    node.isExpanded = true;
                    this.folderToggled.emit(node);
                }, this.dragExpandDelay);
            }
        }
    }

    onDragLeave(_event: DragEvent, node: StorageItem): void {
        if (this.dropTarget()?.path === node.path) {
            this.dropTarget.set(null);
            this.clearDragExpandTimer();
        }
    }

    onDrop(event: DragEvent, node: StorageItem): void {
        event.preventDefault();
        event.stopPropagation();

        const dragged = this.draggedItem();
        if (!dragged || node.type !== 'folder' || !this.isValidDropTarget(dragged, node)) {
            this.resetDragState();
            return;
        }

        this.contextAction.emit({ action: 'move', item: dragged, targetPath: node.path });
        this.resetDragState();
    }

    onDragEnd(): void {
        this.resetDragState();
    }

    onRootDragOver(event: DragEvent): void {
        event.preventDefault();
        event.dataTransfer!.dropEffect = 'move';

        const dragged = this.draggedItem();
        if (!dragged || this.getParentPath(dragged.path) === '') {
            this.dropTargetRoot.set(false);
            return;
        }
        this.dropTarget.set(null);
        this.dropTargetRoot.set(true);
    }

    onRootDragLeave(event: DragEvent): void {
        const related = event.relatedTarget as HTMLElement | null;
        const target = event.currentTarget as HTMLElement;
        if (!related || !target.contains(related)) {
            this.dropTargetRoot.set(false);
        }
    }

    onRootDrop(event: DragEvent): void {
        event.preventDefault();
        event.stopPropagation();

        const dragged = this.draggedItem();
        if (!dragged || this.getParentPath(dragged.path) === '') {
            this.resetDragState();
            return;
        }

        this.contextAction.emit({ action: 'move', item: dragged, targetPath: '/' });
        this.resetDragState();
    }

    isDropTarget(node: StorageItem): boolean {
        return this.dropTarget()?.path === node.path;
    }

    trackByPath(_index: number, item: StorageItem): string {
        return item.path;
    }

    private resetDragState(): void {
        this.draggedItem.set(null);
        this.dropTarget.set(null);
        this.dropTargetRoot.set(false);
        this.clearDragExpandTimer();
    }

    private clearDragExpandTimer(): void {
        if (this.dragExpandTimer) {
            clearTimeout(this.dragExpandTimer);
            this.dragExpandTimer = null;
        }
    }

    private isValidDropTarget(dragged: StorageItem, target: StorageItem): boolean {
        if (target.path === dragged.path) return false;
        if (target.path.startsWith(dragged.path + '/')) return false;
        if (target.path === this.getParentPath(dragged.path)) return false;
        return true;
    }

    private getParentPath(path: string): string {
        const idx = path.lastIndexOf('/');
        return idx >= 0 ? path.substring(0, idx) : '';
    }

    private updateSelection(event: MouseEvent, item: StorageItem): void {
        const path = item.path;
        const isCtrlOrMeta = event.ctrlKey || event.metaKey;
        const isShift = event.shiftKey;
        const currentSelection = new Set(this.selectedPaths());

        if (isShift && this.selectionAnchorPath) {
            const visibleNodes = this.collectVisibleNodes(this.items());
            const startIndex = visibleNodes.findIndex((n) => n.path === this.selectionAnchorPath);
            const endIndex = visibleNodes.findIndex((n) => n.path === path);
            if (startIndex !== -1 && endIndex !== -1) {
                const [from, to] = startIndex < endIndex ? [startIndex, endIndex] : [endIndex, startIndex];
                const ranged = visibleNodes.slice(from, to + 1);
                this.setSelectedPaths(new Set(ranged.map((n) => n.path)));
                return;
            }
        }

        if (isCtrlOrMeta) {
            if (currentSelection.has(path)) {
                currentSelection.delete(path);
            } else {
                currentSelection.add(path);
            }
            this.setSelectedPaths(currentSelection);
            this.selectionAnchorPath = path;
            return;
        }

        this.setSelectedPaths(new Set([path]));
        this.selectionAnchorPath = path;
    }

    private setSelectedPaths(paths: Set<string>): void {
        this.selectedPaths.set(paths);
        const visible = this.collectVisibleNodes(this.items());
        this.selectionChange.emit(visible.filter((n) => paths.has(n.path)));
    }

    private collectVisibleNodes(nodes: StorageItem[]): StorageItem[] {
        const flat: StorageItem[] = [];
        for (const node of nodes) {
            flat.push(node);
            if (node.type === 'folder' && node.isExpanded && node.children?.length) {
                flat.push(...this.collectVisibleNodes(node.children));
            }
        }
        return flat;
    }
}
