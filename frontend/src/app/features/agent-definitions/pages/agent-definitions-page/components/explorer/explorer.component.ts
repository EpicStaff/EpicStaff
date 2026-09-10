import {
    afterRenderEffect,
    ChangeDetectionStrategy,
    Component,
    ElementRef,
    HostBinding,
    inject,
    output,
    Signal,
    signal,
    viewChild,
} from '@angular/core';
import { AppSvgIconComponent } from '@shared/components';
import { DragHoverDirective, ResizableSectionDirective, ResizableSidebarDirective } from '@shared/directives';
import { SectionHeightService, SidebarWidthService } from '@shared/services';

import { StorageItem } from '../../../../../files/models/storage.models';
import { StorageDragService } from '../../../../../files/services/storage-drag.service';
import { ExplorerSectionId } from '../../../../models/explorer.model';
import { BranchTreeNode } from '../../../../models/tree-node.model';
import { AgentsPageStore } from '../../../../services/agents-page-store.service';
import { SurfaceDragService } from '../../../../services/surface-drag.service';
import { AgentsSectionComponent } from './agents-section/agents-section.component';
import { BranchesFilterComponent } from './branches-filter/branches-filter.component';
import { ExplorerContextMenuComponent } from './explorer-context-menu/explorer-context-menu.component';
import { ExplorerMenuItem, ExplorerMenuPosition } from './explorer-context-menu/explorer-menu.model';
import { SectionHeaderComponent } from './section-header/section-header.component';
import { StorageSectionComponent } from './storage-section/storage-section.component';
import { SurfacesSectionComponent } from './surfaces-section/surfaces-section.component';

const SIDEBAR_STORAGE_KEY = 'agents';
/**
 * Matches .explorer__section-body--fill's CSS min-height — the floor a resize drag must never push
 * the filling section below. 84 = 3 full tree rows (tree-node.component.scss: .row min-height 28px),
 * so the filling section never bottoms out mid-row.
 */
const FILL_BODY_MIN_HEIGHT = 84;
import {
    ExplorerTreeAttachSurfaceEvent,
    ExplorerTreeMenuEvent,
    ExplorerTreeMenuOpenEvent,
} from './tree-node/tree-node.component';
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
        DragHoverDirective,
        ResizableSectionDirective,
        ResizableSidebarDirective,
    ],
    templateUrl: './explorer.component.html',
    styleUrls: ['./explorer.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class ExplorerComponent {
    protected readonly store: AgentsPageStore = inject(AgentsPageStore);
    private readonly storageDrag = inject(StorageDragService);
    private readonly surfaceDrag = inject(SurfaceDragService);
    private readonly el = inject(ElementRef<HTMLElement>);
    private readonly sidebarWidthService = inject(SidebarWidthService);
    private readonly sectionHeightService = inject(SectionHeightService);
    private readonly sectionOrder: ExplorerSectionId[] = ['agents', 'surfaces', 'storage'];
    private readonly optionalOrder: ExplorerSectionId[] = ['surfaces', 'storage'];
    private readonly sectionHeightSignals = new Map<ExplorerSectionId, Signal<number | null>>();

    protected readonly sidebarStorageKey = SIDEBAR_STORAGE_KEY;
    /** Same floor as the fill body's CSS min-height, so a manual drag can't cut a tree row off either. */
    protected readonly sectionMinHeight = FILL_BODY_MIN_HEIGHT;
    protected readonly sidebarWidth = this.sidebarWidthService.getWidth(SIDEBAR_STORAGE_KEY);

    @HostBinding('style.width.px')
    get hostWidth(): number {
        return this.sidebarWidth();
    }

    /** Feeds FILL_BODY_MIN_HEIGHT to .explorer__section-body--fill's min-height, so the two can't drift apart. */
    @HostBinding('style.--fill-body-min-height')
    protected get fillBodyMinHeightCss(): string {
        return `${FILL_BODY_MIN_HEIGHT}px`;
    }

    protected get hostElement(): HTMLElement {
        return this.el.nativeElement;
    }

    /**
     * Re-clamps agents/surfaces' stored heights once more per render, after the DOM has fully
     * settled from whatever just changed (e.g. Storage's fill role flipping on expand/collapse).
     * `sectionHeight()` below also clamps live during the same change-detection pass that flips
     * a fill role, but at that point an earlier-evaluated sibling in the template can still read
     * a later one's pre-update DOM state — producing a wrong value for one frame that visibly
     * jumps before settling. Read here runs only once the whole tick's DOM writes are committed
     * (accurate measurements), and write reapplies the corrected value before the browser paints,
     * so that wrong frame is never actually shown.
     */
    constructor() {
        afterRenderEffect({
            earlyRead: () => ({
                agents: this.sectionHeight('agents'),
                surfaces: this.sectionHeight('surfaces'),
            }),
            write: (result) => {
                const { agents, surfaces } = result();
                this.applyCorrectedHeight('agents', agents);
                this.applyCorrectedHeight('surfaces', surfaces);
            },
        });
    }

    private applyCorrectedHeight(sectionId: ExplorerSectionId, corrected: number | null): void {
        if (corrected == null) return;
        this.sectionHeightService.setHeight(
            this.sectionHeightKey(sectionId),
            corrected,
            this.sectionMinHeight,
            Number.POSITIVE_INFINITY
        );
    }

    readonly storageSection = viewChild(StorageSectionComponent);

    readonly selectNode = output<BranchTreeNode>();
    readonly selectStorageItem = output<StorageItem>();
    readonly addInSection = output<ExplorerSectionId>();
    readonly close = output<void>();
    readonly treeMenuAction = output<ExplorerTreeMenuEvent>();
    readonly attachSharedSurface = output<ExplorerTreeAttachSurfaceEvent>();

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

    /** Spring-load a collapsed section while a storage item or shared surface is dragged over its header. */
    onSectionDragHover(id: ExplorerSectionId): void {
        if (!this.storageDrag.isDragging() && !this.surfaceDrag.isDragging()) return;
        if (!this.store.isSectionExpanded(id)) this.store.toggleSection(id);
    }

    onStorageSelect(item: StorageItem): void {
        this.selectStorageItem.emit(item);
    }

    onTreeMenuAction(event: ExplorerTreeMenuEvent): void {
        this.treeMenuAction.emit(event);
    }

    onAttachSharedSurface(event: ExplorerTreeAttachSurfaceEvent): void {
        this.attachSharedSurface.emit(event);
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
            this.withStorageSection((s) => s.openCreateFolder());
            return;
        }
        this.addInSection.emit(section);
    }

    onStorageMenu(event: MouseEvent): void {
        this.withStorageSection((s) => s.openMoreMenu(event));
    }

    private withStorageSection(action: (section: StorageSectionComponent) => void): void {
        this.ensureExpanded('storage');
        const existing = this.storageSection();
        if (existing) {
            action(existing);
            return;
        }
        this.store.activateStorage();
        setTimeout(() => {
            const section = this.storageSection();
            if (section) action(section);
        });
    }

    onClose(): void {
        this.close.emit();
    }

    /**
     * Manually-resized height for a non-filling section body, or null if the user never dragged
     * its handle. Re-clamped against the current layout on every read (not just live drags) —
     * a section can flip from filling to fixed-height when a later section expands and claims
     * the fill role, and a height stored under a roomier layout would otherwise push whatever
     * now needs its own floor (e.g. a freshly-opened Storage) off the bottom of the container.
     */
    sectionHeight(sectionId: ExplorerSectionId): number | null {
        if (this.shouldFillBody(sectionId)) return null;
        const stored = this.sectionHeightSignal(sectionId)();
        if (stored == null) return null;
        return Math.min(stored, this.computeMaxHeight(sectionId, this.sectionMinHeight));
    }

    sectionHeightKey(sectionId: ExplorerSectionId): string {
        return `${SIDEBAR_STORAGE_KEY}:${sectionId}`;
    }

    /** Expands a collapsed section as soon as the user starts dragging its resize handle. */
    ensureExpanded(sectionId: ExplorerSectionId): void {
        if (!this.store.isSectionExpanded(sectionId)) {
            this.store.toggleSection(sectionId);
        }
    }

    /**
     * Caps how far a section can grow when dragged, so it can't squeeze any sibling below a
     * usable floor. The last section in `sectionOrder` is reserved even while collapsed: it
     * always becomes the filling section once it's opened, and a drag made while it's closed
     * must still leave it room — otherwise reopening it clips it against the container (it
     * can't get more space back from siblings that already claimed it).
     */
    sectionMaxHeightFn(sectionId: ExplorerSectionId, target: HTMLElement): () => number {
        return () => this.computeMaxHeight(sectionId, target.getBoundingClientRect().height);
    }

    /**
     * How tall `sectionId` can be without squeezing a sibling below its usable floor — the same
     * budget `sectionMaxHeightFn` enforces live during a drag, also used to re-clamp a stored
     * height outside of a drag (see `sectionHeight`). `floor` is the smallest result allowed:
     * a live drag passes the section's current height (never shrink below where the pointer
     * already dragged it to); a static re-clamp passes `sectionMinHeight` instead, so a stale
     * stored value can shrink all the way down to fit.
     */
    private computeMaxHeight(sectionId: ExplorerSectionId, floor: number): number {
        const container = this.el.nativeElement.querySelector('.explorer__sections') as HTMLElement | null;
        if (!container) return Number.POSITIVE_INFINITY;

        let reserved = 0;
        for (const id of this.sectionOrder) {
            if (id === sectionId || !this.store.isSectionVisible(id)) continue;
            const sectionEl = this.el.nativeElement.querySelector(`[data-section-id="${id}"]`) as HTMLElement | null;
            if (!sectionEl) continue;

            if (!this.store.isSectionExpanded(id)) {
                // Collapsed: reserve just the header. Measuring the whole section here would race
                // Angular's own [hidden] update on its body when toggling *this* id is what triggered
                // the recompute — the body briefly still renders its old (expanded) height, over- or
                // under-reserving for one frame and producing a visible jump/settle in a sibling.
                const headerHeight =
                    (sectionEl.firstElementChild as HTMLElement | null)?.getBoundingClientRect().height ?? 0;
                reserved += this.isLastInSectionOrder(id) ? headerHeight + FILL_BODY_MIN_HEIGHT : headerHeight;
            } else if (this.shouldFillBody(id)) {
                // Currently absorbing leftover space — only its guaranteed floor must survive.
                const headerHeight =
                    (sectionEl.firstElementChild as HTMLElement | null)?.getBoundingClientRect().height ?? 0;
                reserved += headerHeight + FILL_BODY_MIN_HEIGHT;
            } else {
                reserved += sectionEl.getBoundingClientRect().height;
            }
        }

        const containerHeight = container.getBoundingClientRect().height;
        return Math.round(Math.max(floor, containerHeight - reserved));
    }

    private isLastInSectionOrder(sectionId: ExplorerSectionId): boolean {
        return this.sectionOrder[this.sectionOrder.length - 1] === sectionId;
    }

    private sectionHeightSignal(sectionId: ExplorerSectionId): Signal<number | null> {
        let sig = this.sectionHeightSignals.get(sectionId);
        if (!sig) {
            sig = this.sectionHeightService.getHeight(this.sectionHeightKey(sectionId), this.sectionMinHeight);
            this.sectionHeightSignals.set(sectionId, sig);
        }
        return sig;
    }

    shouldFillBody(sectionId: ExplorerSectionId): boolean {
        if (!this.store.isSectionExpanded(sectionId)) return false;
        // Only the lowest expanded section absorbs leftover height and scrolls.
        // Upper ones size to content so rows are never painted under the next header.
        return this.lastExpandedVisibleSection() === sectionId;
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

    private lastExpandedVisibleSection(): ExplorerSectionId | null {
        let last: ExplorerSectionId | null = null;
        for (const id of this.sectionOrder) {
            if (this.store.isSectionVisible(id) && this.store.isSectionExpanded(id)) {
                last = id;
            }
        }
        return last;
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
