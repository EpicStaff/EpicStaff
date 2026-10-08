import { NgTemplateOutlet } from '@angular/common';
import {
    ChangeDetectionStrategy,
    Component,
    computed,
    DestroyRef,
    effect,
    ElementRef,
    inject,
    input,
    output,
    signal,
    untracked,
    viewChild,
} from '@angular/core';
import { MatTooltipModule } from '@angular/material/tooltip';
import { AppSvgIconComponent } from '@shared/components';
import { HasPermissionDirective, TooltipOnOverflowDirective } from '@shared/directives';
import { ActionCode, ResourceCode } from '@shared/models';

import { PermissionsService } from '../../../../../../../../services/auth/permissions.service';
import { canImportStorageToKnowledge } from '../../../../../../../knowledge-sources/helpers/storage-import.util';
import { StorageItem } from '../../../../../../models/storage.models';
import { StorageDragService } from '../../../../../../services/storage-drag.service';
import { getFileExtension } from '../../../../../../utils/storage-file.utils';

@Component({
    selector: 'app-storage-tree',
    imports: [
        NgTemplateOutlet,
        AppSvgIconComponent,
        MatTooltipModule,
        HasPermissionDirective,
        TooltipOnOverflowDirective,
    ],
    templateUrl: './storage-tree.component.html',
    styleUrls: ['./storage-tree.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class StorageTreeComponent {
    private readonly storageDrag = inject(StorageDragService);
    private readonly permissionsService = inject(PermissionsService);

    items = input<StorageItem[]>([]);
    showHeader = input<boolean>(true);
    /** Offers "Add to collection…"; only the Files → Storage page turns this on. */
    enableKnowledgeImport = input<boolean>(false);
    /**
     * The unfiltered tree, when `items` is a filtered view (e.g. search). Selection bookkeeping
     * uses it so a search never deselects hidden items. Defaults to `items`.
     */
    loadedItems = input<StorageItem[] | undefined>(undefined);
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

    private readonly renameInputRef = viewChild<ElementRef<HTMLInputElement>>('renameInput');
    private readonly listElRef = viewChild<ElementRef<HTMLElement>>('listEl');

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

    draggedItem = signal<StorageItem | null>(null);
    draggedItems = signal<StorageItem[]>([]);
    dropTarget = signal<StorageItem | null>(null);
    dropTargetRoot = signal<boolean>(false);
    private dragExpandTimer: ReturnType<typeof setTimeout> | null = null;
    private readonly dragExpandDelay = 700;

    protected readonly canAddToCollection = computed(
        () => this.enableKnowledgeImport() && canImportStorageToKnowledge(this.permissionsService)
    );

    /** The drag service can end a drag on its own (safety net); drop this tree's local drag state too. */
    private readonly syncLocalDragStateWithService = effect(() => {
        if (this.storageDrag.isDragging()) return;
        untracked(() => {
            if (this.draggedItems().length > 0) this.clearLocalDragState();
        });
    });

    /** Deselects only paths that truly disappeared (e.g. after a refresh); a search filter never deselects. */
    /** Everything the tree has loaded, ignoring any filter applied to `items`. */
    private readonly allLoadedItems = computed(() => this.loadedItems() ?? this.items());

    private readonly pruneSelectionToLoadedItems = effect(() => {
        const loadedPaths = new Set(this.collectLoadedNodes(this.allLoadedItems()).map((node) => node.path));
        untracked(() => {
            const selected = this.selectedPaths();
            const kept = [...selected].filter((path) => loadedPaths.has(path));
            if (kept.length !== selected.size) this.setSelectedPaths(new Set(kept));
        });
    });

    constructor() {
        // A destroyed drag source never fires `dragend`, so end the drag here.
        inject(DestroyRef).onDestroy(() => {
            this.clearDragExpandTimer();
            if (this.draggedItems().length > 0) this.storageDrag.end();
        });
    }

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
        const listEl = this.listElRef()?.nativeElement;
        if (!listEl) return;
        const el = listEl.querySelector(`[data-path="${CSS.escape(item.path)}"]`) as HTMLElement | null;
        el?.scrollIntoView({ behavior: 'smooth', block: 'center' });
    }

    startRename(item: StorageItem): void {
        this.renamingFromPath = item.path || item.name;
        this.renameValue = item.name;

        const path = item.path || item.name;
        const listEl = this.listElRef()?.nativeElement;
        const itemEl =
            (this.hoveredItemEl?.getAttribute('data-path') === path ? this.hoveredItemEl : null) ??
            (listEl?.querySelector(`[data-path="${CSS.escape(path)}"]`) as HTMLElement | null);
        if (itemEl && listEl) {
            itemEl.scrollIntoView({ block: 'nearest' });
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
            this.renameInputRef()?.nativeElement.focus();
            this.renameInputRef()?.nativeElement.select();
        });
    }

    /**
     * Like startRename, but waits for the item's row to actually exist in the DOM first.
     * Needed right after a tree reload (e.g. after grouping), where the row may not be
     * rendered yet — starting the rename immediately would leave renamePos unset and the
     * overlay would fall back to a default position instead of the item's real row.
     */
    startRenameWhenReady(item: StorageItem, retriesLeft = 20): void {
        const path = item.path || item.name;
        const listEl = this.listElRef()?.nativeElement;
        const exists = listEl?.querySelector(`[data-path="${CSS.escape(path)}"]`);
        if (exists || retriesLeft <= 0) {
            this.startRename(item);
            return;
        }
        setTimeout(() => this.startRenameWhenReady(item, retriesLeft - 1), 50);
    }

    onContextMenuAction(action: string): void {
        const item = this.contextMenuItem();
        if (!item) return;

        if (action === 'rename') {
            this.startRename(item);
        } else if (action === 'group-selected') {
            this.startGrouping();
        } else if (action === 'delete') {
            const selectedSet = this.selectedPaths();
            const selectedItems = this.collectVisibleNodes(this.items()).filter((node) => selectedSet.has(node.path));
            if (selectedItems.length > 1) {
                this.contextAction.emit({ action: 'delete-selected', item, selectedItems });
            } else {
                this.contextAction.emit({ action, item });
            }
        } else if (action === 'add-to-collection') {
            this.contextAction.emit({ action, item, selectedItems: this.resolveSelectionForAction(item) });
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

    canGroupSelected(): boolean {
        return this.getGroupableItems().length >= 2;
    }

    startGrouping(): void {
        const items = this.getGroupableItems();
        if (items.length < 2) {
            return;
        }

        this.contextAction.emit({
            action: 'group-selected',
            item: items[0],
            selectedItems: items,
        });
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
        const menuHeight = 140;
        const x = Math.min(rect.left, window.innerWidth - menuWidth - 8);
        const below = rect.bottom + 4;
        const y = below + menuHeight > window.innerHeight ? Math.max(8, rect.top - menuHeight - 4) : below;
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

    private getSelectedItems(): StorageItem[] {
        const selectedSet = this.selectedPaths();
        return this.collectVisibleNodes(this.items()).filter((node) => selectedSet.has(node.path));
    }

    private getGroupableItems(): StorageItem[] {
        const items = this.pruneNestedItems(this.getSelectedItems());
        if (items.length < 2) {
            return [];
        }
        const parent = this.getParentPath(items[0].path);
        return items.every((item) => this.getParentPath(item.path) === parent) ? items : [];
    }

    onDragStart(event: DragEvent, item: StorageItem): void {
        if (this.renamingItem()) {
            event.preventDefault();
            return;
        }
        const items = this.resolveSelectionForAction(item);
        event.dataTransfer!.effectAllowed = 'copyMove';
        event.dataTransfer!.setData('text/plain', items.map((i) => i.path).join('\n'));
        this.draggedItem.set(item);
        this.draggedItems.set(items);
        // Native DnD suppresses mouseleave, so the row's hover actions would stay "visible" for
        // the whole drag — even through the hidden, kept-alive Storage page after a tab switch.
        this.hoveredItem.set(null);
        this.storageDrag.start(item, items);
    }

    /**
     * A folder row is its own drop target; a file row resolves to its parent folder
     * (or the root). The event never bubbles to the root handler from a row, so a row
     * can no longer trigger a false "move to root" outline.
     */
    onDragOver(event: DragEvent, node: StorageItem): void {
        const dragged = this.draggedItems();
        if (dragged.length === 0) return;

        event.preventDefault();
        event.stopPropagation();

        const target = this.resolveDropTarget(node);
        if (!target || !this.isValidDropTargetForItems(dragged, target.path)) {
            event.dataTransfer!.dropEffect = 'none';
            this.dropTarget.set(null);
            this.dropTargetRoot.set(false);
            this.clearDragExpandTimer();
            return;
        }

        event.dataTransfer!.dropEffect = 'move';

        if (!target.folder) {
            this.dropTarget.set(null);
            this.clearDragExpandTimer();
            this.dropTargetRoot.set(true);
            return;
        }

        this.dropTargetRoot.set(false);
        const folder = target.folder;
        if (this.dropTarget()?.path !== folder.path) {
            this.dropTarget.set(folder);
            this.clearDragExpandTimer();
            if (!folder.isExpanded) {
                this.dragExpandTimer = setTimeout(() => {
                    folder.isExpanded = true;
                    this.folderToggled.emit(folder);
                }, this.dragExpandDelay);
            }
        }
    }

    /**
     * Keeps the highlight while the pointer moves inside the row, or onto another row that
     * resolves to the same folder (e.g. between sibling files), so it does not flicker.
     */
    onDragLeave(event: DragEvent, node: StorageItem): void {
        const target = this.resolveDropTarget(node);
        if (!target?.folder || this.dropTarget()?.path !== target.folder.path) return;

        const row = event.currentTarget as HTMLElement | null;
        const related = event.relatedTarget as Node | null;
        if (row && related && row.contains(related)) return;
        if (this.resolveDropTargetOfElement(related)?.path === target.path) return;

        this.dropTarget.set(null);
        this.clearDragExpandTimer();
    }

    onDrop(event: DragEvent, node: StorageItem): void {
        const dragged = this.draggedItems();
        if (dragged.length === 0) return;

        event.preventDefault();
        event.stopPropagation();

        const target = this.resolveDropTarget(node);
        const movable = target ? this.filterMovableTo(dragged, target.path) : [];
        if (!target || movable.length === 0) {
            this.resetDragState();
            return;
        }

        this.contextAction.emit({
            action: 'move',
            item: movable[0],
            selectedItems: movable,
            targetPath: target.path || '/',
        });
        this.resetDragState();
    }

    onDragEnd(): void {
        this.resetDragState();
    }

    onRootDragOver(event: DragEvent): void {
        const dragged = this.draggedItems();
        // External (OS file) drags pass through to the page's upload area.
        if (dragged.length === 0) return;

        event.preventDefault();
        event.dataTransfer!.dropEffect = 'move';

        if (dragged.every((item) => this.getParentPath(item.path) === '')) {
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
        const dragged = this.draggedItems();
        if (dragged.length === 0) return;

        event.preventDefault();
        event.stopPropagation();

        const movable = this.filterMovableTo(dragged, '/');
        if (movable.length === 0) {
            this.resetDragState();
            return;
        }

        this.contextAction.emit({
            action: 'move',
            item: movable[0],
            selectedItems: movable,
            targetPath: '/',
        });
        this.resetDragState();
    }

    isDropTarget(node: StorageItem): boolean {
        return this.dropTarget()?.path === node.path;
    }

    isDraggingItem(node: StorageItem): boolean {
        return this.draggedItems().some((item) => item.path === node.path);
    }

    trackByPath(_index: number, item: StorageItem): string {
        return item.path;
    }

    private resetDragState(): void {
        this.clearLocalDragState();
        this.storageDrag.end();
    }

    private clearLocalDragState(): void {
        this.draggedItem.set(null);
        this.draggedItems.set([]);
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

    /**
     * The grabbed row alone, or — when it is part of a multi-selection — the whole selection.
     * Walks every loaded node of the unfiltered tree (not only visible ones), so selected items
     * inside a collapsed folder or hidden by a search are included. The selection is pruned to loaded paths
     * whenever the tree data changes (`pruneSelectionToLoadedItems`), so it never names an item
     * the tree no longer has.
     */
    private resolveSelectionForAction(grabbed: StorageItem): StorageItem[] {
        const selected = this.selectedPaths();
        if (!selected.has(grabbed.path) || selected.size <= 1) {
            return [grabbed];
        }
        const selectedItems = this.collectLoadedNodes(this.allLoadedItems()).filter((node) => selected.has(node.path));
        return this.pruneNestedItems(selectedItems);
    }

    /** Root is `{ path: '', folder: null }`; null means the row has no resolvable drop target. */
    private resolveDropTarget(node: StorageItem): { path: string; folder: StorageItem | null } | null {
        if (node.type === 'folder') {
            return { path: node.path, folder: node };
        }
        const parentPath = this.getParentPath(node.path);
        if (!parentPath) {
            return { path: '', folder: null };
        }
        const parent = this.findNodeByPath(this.items(), parentPath);
        return parent ? { path: parentPath, folder: parent } : null;
    }

    private resolveDropTargetOfElement(element: Node | null): { path: string; folder: StorageItem | null } | null {
        const row = element instanceof Element ? element.closest('[data-path]') : null;
        const path = row?.getAttribute('data-path');
        const node = path ? this.findNodeByPath(this.items(), path) : undefined;
        return node ? this.resolveDropTarget(node) : null;
    }

    private findNodeByPath(nodes: StorageItem[], path: string): StorageItem | undefined {
        for (const node of nodes) {
            if (node.path === path) return node;
            if (node.children?.length && path.startsWith(`${node.path}/`)) {
                const found = this.findNodeByPath(node.children, path);
                if (found) return found;
            }
        }
        return undefined;
    }

    private pruneNestedItems(items: StorageItem[]): StorageItem[] {
        const paths = items.map((item) => item.path);
        return items.filter((item) => !paths.some((path) => path !== item.path && item.path.startsWith(`${path}/`)));
    }

    private filterMovableTo(items: StorageItem[], targetPath: string): StorageItem[] {
        const normalizedTarget = targetPath === '/' ? '' : targetPath;
        return items.filter((item) => {
            if (this.getParentPath(item.path) === normalizedTarget) return false;
            if (normalizedTarget === item.path || normalizedTarget.startsWith(`${item.path}/`)) return false;
            return true;
        });
    }

    private isValidDropTargetForItems(dragged: StorageItem[], targetPath: string): boolean {
        return this.filterMovableTo(dragged, targetPath).length > 0;
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

    private collectLoadedNodes(nodes: StorageItem[]): StorageItem[] {
        const flat: StorageItem[] = [];
        for (const node of nodes) {
            flat.push(node);
            if (node.type === 'folder' && node.children?.length) {
                flat.push(...this.collectLoadedNodes(node.children));
            }
        }
        return flat;
    }

    protected readonly ResourceCode = ResourceCode;
    protected readonly ActionCode = ActionCode;
}
