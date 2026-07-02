import { ChangeDetectionStrategy, Component, inject, output, signal, viewChild } from '@angular/core';
import { AppSvgIconComponent } from '@shared/components';

import { StorageItem } from '../../../../../files/models/storage.models';
import { ExplorerSectionId } from '../../../../models/explorer.model';
import { BranchTreeNode } from '../../../../models/tree-node.model';
import { AgentsPageStore } from '../../../../services/agents-page-store.service';
import { AgentsSectionComponent } from './agents-section/agents-section.component';
import { BranchesFilterComponent } from './branches-filter/branches-filter.component';
import { ExplorerContextMenuComponent } from './explorer-context-menu/explorer-context-menu.component';
import { ExplorerMenuItem, ExplorerMenuPosition } from './explorer-context-menu/explorer-menu.model';
import { SectionHeaderComponent } from './section-header/section-header.component';
import { StorageSectionComponent } from './storage-section/storage-section.component';
import { SurfacesSectionComponent } from './surfaces-section/surfaces-section.component';
import { ExplorerTreeMenuEvent, ExplorerTreeMenuOpenEvent } from './tree-node/tree-node.component';
import { TreeSearchComponent } from './tree-search/tree-search.component';

@Component({
    selector: 'app-explorer',
    imports: [
        AppSvgIconComponent,
        TreeSearchComponent,
        SectionHeaderComponent,
        BranchesFilterComponent,
        AgentsSectionComponent,
        SurfacesSectionComponent,
        StorageSectionComponent,
        ExplorerContextMenuComponent,
    ],
    templateUrl: './explorer.component.html',
    styleUrls: ['./explorer.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class ExplorerComponent {
    protected readonly store: AgentsPageStore = inject(AgentsPageStore);
    private readonly orderedSectionIds: ExplorerSectionId[] = ['agents', 'surfaces', 'storage'];
    private readonly optionalOrder: ExplorerSectionId[] = ['surfaces', 'storage'];

    readonly storageSection = viewChild(StorageSectionComponent);

    readonly selectNode = output<BranchTreeNode>();
    readonly selectStorageItem = output<StorageItem>();
    readonly addInSection = output<ExplorerSectionId>();
    readonly close = output<void>();
    readonly treeMenuAction = output<ExplorerTreeMenuEvent>();

    readonly filterOpen = signal<boolean>(false);

    readonly menuOpen = signal<boolean>(false);
    readonly menuPosition = signal<ExplorerMenuPosition>({ x: 0, y: 0 });
    readonly menuItems = signal<ExplorerMenuItem[]>([]);
    private menuNode: BranchTreeNode | null = null;

    toggleFilter(): void {
        this.filterOpen.update((v) => !v);
    }

    onFilterSave(ids: Set<ExplorerSectionId>): void {
        this.store.setVisibleSections(ids);
        this.filterOpen.set(false);
    }

    onFilterCancel(): void {
        this.filterOpen.set(false);
    }

    onSearchChange(q: string): void {
        this.store.setSearch(q);
    }

    onSelect(node: BranchTreeNode): void {
        this.selectNode.emit(node);
    }

    onStorageSelect(item: StorageItem): void {
        this.selectStorageItem.emit(item);
    }

    onTreeMenuAction(event: ExplorerTreeMenuEvent): void {
        this.treeMenuAction.emit(event);
    }

    onTreeMenuOpen(event: ExplorerTreeMenuOpenEvent): void {
        this.menuNode = event.node;
        this.menuItems.set(event.items);
        this.menuPosition.set(event.position);
        this.menuOpen.set(true);
    }

    onMenuItemAction(action: string): void {
        const node = this.menuNode;
        this.closeMenu();
        if (node) this.treeMenuAction.emit({ node, action });
    }

    closeMenu(): void {
        this.menuOpen.set(false);
        this.menuNode = null;
    }

    onAdd(section: ExplorerSectionId): void {
        if (section === 'storage') {
            this.storageSection()?.openCreateFolder();
            return;
        }
        this.addInSection.emit(section);
    }

    onStorageMenu(event: MouseEvent): void {
        this.storageSection()?.openMoreMenu(event);
    }

    onClose(): void {
        this.close.emit();
    }

    shouldFillBody(sectionId: ExplorerSectionId): boolean {
        return this.store.isSectionExpanded(sectionId) && this.expandedVisibleCount() > 1;
    }

    isBottomSection(sectionId: ExplorerSectionId): boolean {
        const idx = this.optionalVisibleOrder().indexOf(sectionId);
        if (idx < 0) return false;
        const lastExpandedIdx = this.lastExpandedOptionalIndex();
        if (lastExpandedIdx < 0) return true;
        return idx > lastExpandedIdx;
    }

    isBottomAnchor(sectionId: ExplorerSectionId): boolean {
        if (!this.isBottomSection(sectionId)) return false;
        return this.optionalVisibleOrder().find((id) => this.isBottomSection(id)) === sectionId;
    }

    private expandedVisibleCount(): number {
        return this.orderedSectionIds.filter(
            (id) => this.store.isSectionVisible(id) && this.store.isSectionExpanded(id)
        ).length;
    }

    private optionalVisibleOrder(): ExplorerSectionId[] {
        return this.optionalOrder.filter((id) => this.store.isSectionVisible(id));
    }

    private lastExpandedOptionalIndex(): number {
        const visible = this.optionalVisibleOrder();
        let lastExpandedIdx = -1;
        for (let i = 0; i < visible.length; i++) {
            if (this.store.isSectionExpanded(visible[i])) lastExpandedIdx = i;
        }
        return lastExpandedIdx;
    }
}
