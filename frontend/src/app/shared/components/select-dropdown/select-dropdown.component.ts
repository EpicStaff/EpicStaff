// eslint-disable-next-line simple-import-sort/imports
import { Overlay, OverlayPositionBuilder, OverlayRef } from '@angular/cdk/overlay';
import { TemplatePortal } from '@angular/cdk/portal';
import {
    afterNextRender,
    ChangeDetectionStrategy,
    Component,
    computed,
    DestroyRef,
    effect,
    ElementRef,
    inject,
    Injector,
    input,
    model,
    output,
    signal,
    TemplateRef,
    untracked,
    ViewChild,
    ViewContainerRef,
    contentChild,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { Observable } from 'rxjs';

import { AppSvgIconComponent } from '../app-svg-icon/app-svg-icon.component';
import { ButtonComponent } from '../buttons';
import { CheckboxComponent } from '../checkbox/checkbox.component';
import { SelectDropdownTriggerDirective } from './select-dropdown-trigger.directive';
import {
    SelectDropdownHeaderAction,
    SelectDropdownListItem,
    SelectDropdownMode,
    SelectDropdownSelectionMode,
    SelectDropdownTab,
    SelectDropdownTreeNode,
} from './select-dropdown.model';

type RuntimeTreeNode = Omit<SelectDropdownTreeNode, 'children'> & {
    isExpanded: boolean;
    isLoading: boolean;
    isLoaded: boolean;
    children: RuntimeTreeNode[];
};

interface VisibleRow {
    node: RuntimeTreeNode;
    level: number;
}

@Component({
    selector: 'app-select-dropdown',
    standalone: true,
    imports: [AppSvgIconComponent, CheckboxComponent, ButtonComponent],
    templateUrl: './select-dropdown.component.html',
    styleUrls: ['./select-dropdown.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class SelectDropdownComponent {
    mode = input<SelectDropdownMode>('list');
    selectionMode = input<SelectDropdownSelectionMode>('multiple');

    items = input<SelectDropdownListItem[]>([]);
    nodes = input<SelectDropdownTreeNode[]>([]);
    loadChildren = input<((node: SelectDropdownTreeNode) => Observable<SelectDropdownTreeNode[]>) | null>(null);

    searchable = input<boolean>(true);
    searchPlaceholder = input<string>('Search item...');
    selectedOnTop = input<boolean>(false);
    panelWidth = input<number | null>(null);
    minPanelWidth = input<number | null>(null);
    maxPanelWidth = input<string | number | null>(null);
    /** Panel max-height. Number => px; string passed through (e.g. '80vh'). Null keeps the CSS default. */
    maxPanelHeight = input<string | number | null>(null);
    emptyText = input<string>('No results');

    /**
     * Opt-in in-panel tabs. When non-empty the panel header renders a tab strip
     * (below the search); the host swaps `items`/`nodes` on `tabChange`. Empty
     * (default) keeps the plain single-list panel unchanged.
     */
    tabs = input<SelectDropdownTab[]>([]);
    /** Active tab id (two-way). Defaults to the first tab when tabs are provided. */
    activeTabId = model<string | null>(null);
    tabChange = output<string>();
    draftChange = output<unknown[]>();

    /** Optional action button shown in the tab strip (hidden when null). */
    headerAction = input<SelectDropdownHeaderAction | null>(null);
    headerActionClick = output<string>();

    /**
     * Selected values. For mode='list' these are SelectItem.value[]; for mode='tree'
     * these are leaf-file ids only — checked empty folders live in internal state and
     * do NOT appear here.
     */
    selected = model<unknown[]>([]);
    selectionChange = output<unknown[]>();
    openedChange = output<boolean>();

    readonly triggerDir = contentChild(SelectDropdownTriggerDirective);
    @ViewChild('defaultTrigger') defaultTrigger?: ElementRef<HTMLElement>;
    @ViewChild('panelTemplate') panelTemplate!: TemplateRef<unknown>;

    private readonly overlay = inject(Overlay);
    private readonly overlayPositionBuilder = inject(OverlayPositionBuilder);
    private readonly vcr = inject(ViewContainerRef);
    private readonly destroyRef = inject(DestroyRef);
    private readonly injector = inject(Injector);
    private overlayRef: OverlayRef | null = null;

    // Largest visible-row count seen since the panel opened. Repositioning the overlay
    // (to claim more space) only fires when the count grows past this — so expanding a
    // folder can enlarge the panel, but collapsing never shrinks it (no jumpiness).
    private maxRowsSinceOpen = 0;
    // Panel min-height floor (px) that ratchets up as rows expand; keeps the panel from
    // wrapping smaller when the tree collapses. Reset to 0 on each open.
    private readonly stickyMinHeight = signal(0);

    readonly isOpen = signal(false);
    readonly search = signal('');

    // Draft selection for multiple mode (committed only on Save Changes).
    private readonly draft = signal<unknown[]>([]);
    private readonly draftFolderIds = signal<Set<string | number>>(new Set());

    // selected-on-top: order frozen on open so rows don't jump while clicking.
    private readonly frozenOrder = signal<SelectDropdownListItem[] | null>(null);

    private readonly treeRoots = signal<RuntimeTreeNode[]>([]);
    private readonly parentById = signal<Map<string | number, string | number | null>>(new Map());

    private readonly selectedSet = computed(() => new Set(this.selected()));
    private readonly draftSet = computed(() => new Set(this.draft()));

    /** Active selection set: draft in multiple, committed in single. */
    private readonly activeSet = computed(() =>
        this.selectionMode() === 'multiple' ? this.draftSet() : this.selectedSet()
    );

    /** True when the draft holds no selection (drives the Clear Filter accent border). */
    readonly draftEmpty = computed(() => this.draft().length === 0 && this.draftFolderIds().size === 0);

    /** CSS max-height for the panel; number inputs become px, clamped to the viewport. */
    readonly panelMaxHeight = computed<string | null>(() => {
        const h = this.maxPanelHeight();
        if (h == null) return null;
        return typeof h === 'number' ? `min(${h}px, 90vh)` : h;
    });

    /** Ratcheting min-height (px) so the panel never shrinks back within an open session. */
    readonly panelMinHeight = computed<number | null>(() => this.stickyMinHeight() || null);

    constructor() {
        // Clone nodes() into a mutable runtime tree only when the input ref changes,
        // so user expand state survives unrelated change-detection cycles.
        effect(() => {
            const roots = this.nodes();
            untracked(() => {
                const cloned = roots.map((n) => this.cloneNode(n));
                this.treeRoots.set(cloned);
                this.rebuildParentMap(cloned);
            });
        });

        // With tabs, switching tabs swaps both items() and the controlled selected()
        // asynchronously (the host reacts to tabChange). Keep the open panel in sync
        // with the new tab: re-seed the multiple-mode draft from selected() and
        // re-freeze the selected-on-top order once the new catalog arrives.
        effect(() => {
            // Track both so a tab switch (which swaps each) re-runs this.
            this.items();
            const selected = this.selected();
            untracked(() => {
                if (!this.isOpen() || this.mode() !== 'list') return;
                if (this.selectionMode() === 'multiple') {
                    this.draft.set([...selected]);
                    this.draftFolderIds.set(new Set());
                }
                if (this.selectedOnTop()) this.buildFrozenOrder();
            });
        });

        // Grow-only sizing: when expanding rows makes the panel need more room, re-run
        // CDK's flexible positioning so it can claim the extra space (flip above, push),
        // then pin the panel's achieved height as a min-height floor. Collapsing rows
        // never triggers this, and the floor keeps the panel from wrapping smaller — so
        // the panel only ever grows within a single open session (no jumpiness).
        effect(() => {
            const rows = this.visibleRowCount();
            const open = this.isOpen();
            untracked(() => {
                if (!open) return;
                if (rows <= this.maxRowsSinceOpen) return;
                this.maxRowsSinceOpen = rows;
                afterNextRender(
                    () => {
                        this.overlayRef?.updatePosition();
                        this.pinPanelFloor();
                    },
                    { injector: this.injector }
                );
            });
        });
    }

    /** Ratchet the panel's min-height up to its current rendered height (never down). */
    private pinPanelFloor(): void {
        const panel = this.overlayRef?.overlayElement.querySelector<HTMLElement>('.select-dropdown__panel');
        if (!panel) return;
        const h = panel.offsetHeight;
        if (h > this.stickyMinHeight()) this.stickyMinHeight.set(h);
    }

    // ============ OPEN / CLOSE / OVERLAY ============
    toggle(): void {
        this.isOpen() ? this.close() : this.openDropdown();
    }

    openDropdown(): void {
        const triggerEl = this.triggerDir()?.elementRef ?? this.defaultTrigger!;
        if (!this.overlayRef) {
            // Adaptive placement: prefer below the trigger, fall back to above, then
            // beside/centered so a tall panel still finds room near a viewport edge.
            // withFlexibleDimensions + withPush let CDK shrink/nudge the panel to fit.
            const positionStrategy = this.overlayPositionBuilder
                .flexibleConnectedTo(triggerEl)
                .withFlexibleDimensions(true)
                // Without this, CDK clamps the panel to its first-open height on every
                // updatePosition() (Math.min vs _lastBoundingBoxSize) — so expanding a
                // folder just adds an inner scrollbar instead of using the free space
                // down to the viewport edge. growAfterOpen lets it re-expand.
                .withGrowAfterOpen(true)
                .withViewportMargin(8)
                .withPush(true)
                .withPositions([
                    { originX: 'start', originY: 'bottom', overlayX: 'start', overlayY: 'top', offsetY: 4 },
                    { originX: 'start', originY: 'top', overlayX: 'start', overlayY: 'bottom', offsetY: -4 },
                    { originX: 'end', originY: 'bottom', overlayX: 'end', overlayY: 'top', offsetY: 4 },
                    { originX: 'end', originY: 'top', overlayX: 'end', overlayY: 'bottom', offsetY: -4 },
                    { originX: 'end', originY: 'center', overlayX: 'start', overlayY: 'center', offsetX: 4 },
                    { originX: 'start', originY: 'center', overlayX: 'end', overlayY: 'center', offsetX: -4 },
                ]);

            // Panel width follows the trigger element unless panelWidth is set.
            this.overlayRef = this.overlay.create({
                positionStrategy,
                scrollStrategy: this.overlay.scrollStrategies.reposition(),
                hasBackdrop: true,
                backdropClass: 'transparent-backdrop',
                width: this.panelWidth() ?? triggerEl.nativeElement.offsetWidth,
                minWidth: this.minPanelWidth() ?? undefined,
                maxWidth: this.maxPanelWidth() ?? undefined,
            });

            this.overlayRef
                .backdropClick()
                .pipe(takeUntilDestroyed(this.destroyRef))
                .subscribe(() => this.close());
        }

        this.search.set('');
        if (this.selectionMode() === 'multiple') {
            this.draft.set([...this.selected()]);
            this.draftFolderIds.set(new Set());
        }
        if (this.mode() === 'list' && this.selectedOnTop()) {
            this.buildFrozenOrder();
        }

        // Baseline for grow-only sizing; the panel opens sized to current content.
        this.maxRowsSinceOpen = untracked(() => this.visibleRowCount());
        this.stickyMinHeight.set(0);

        this.overlayRef.attach(new TemplatePortal(this.panelTemplate, this.vcr));
        this.isOpen.set(true);
        this.openedChange.emit(true);
    }

    close(): void {
        this.overlayRef?.detach();
        this.isOpen.set(false);
        this.frozenOrder.set(null);
        this.openedChange.emit(false);
    }

    // ============ FOOTER (multiple) ============
    saveChanges(): void {
        const next = [...this.draft()];
        this.selected.set(next);
        this.selectionChange.emit(next);
        this.close();
    }

    cancel(): void {
        this.close();
    }

    clearFilter(): void {
        this.draft.set([]);
        this.draftFolderIds.set(new Set());
    }

    // ============ TABS (opt-in) ============
    /** Active tab, defaulting to the first tab when the host hasn't set one. */
    readonly resolvedActiveTabId = computed<string | null>(() => {
        const active = this.activeTabId();
        const tabs = this.tabs();
        if (active && tabs.some((t) => t.id === active)) return active;
        return tabs[0]?.id ?? null;
    });

    selectTab(id: string): void {
        if (id === this.resolvedActiveTabId()) return;
        if (this.selectionMode() === 'multiple') this.draftChange.emit([...this.draft()]);
        this.activeTabId.set(id);
        // Switching catalogs invalidates the frozen selected-on-top order and search.
        this.search.set('');
        this.frozenOrder.set(null);
        this.tabChange.emit(id);
    }

    onHeaderAction(): void {
        const active = this.resolvedActiveTabId();
        this.headerActionClick.emit(active ?? '');
    }

    // ============ LIST ============
    private readonly orderedItems = computed<SelectDropdownListItem[]>(() => {
        const frozen = this.frozenOrder();
        return this.selectedOnTop() && frozen ? frozen : this.items();
    });

    readonly filteredItems = computed<SelectDropdownListItem[]>(() => {
        const q = this.search().trim().toLowerCase();
        const base = this.orderedItems();
        return q ? base.filter((i) => i.name.toLowerCase().includes(q)) : base;
    });

    isItemSelected(item: SelectDropdownListItem): boolean {
        return this.activeSet().has(item.value);
    }

    selectItem(item: SelectDropdownListItem): void {
        if (item.disabled) return;
        if (this.selectionMode() === 'single') {
            this.selected.set([item.value]);
            this.selectionChange.emit([item.value]);
            this.close();
            return;
        }
        const has = this.draftSet().has(item.value);
        this.draft.set(has ? this.draft().filter((v) => v !== item.value) : [...this.draft(), item.value]);
    }

    private buildFrozenOrder(): void {
        const sel = this.selectedSet();
        const all = this.items();
        const checked = all.filter((i) => sel.has(i.value));
        const rest = all.filter((i) => !sel.has(i.value));
        this.frozenOrder.set([...checked, ...rest]);
    }

    // ============ TREE ============
    readonly visibleTree = computed<VisibleRow[]>(() => {
        const q = this.search().trim().toLowerCase();
        if (q) {
            const flat = this.flattenAll(this.treeRoots(), 0);
            const matched = flat.filter((r) => r.node.name.toLowerCase().includes(q));
            const min = matched.reduce((m, r) => Math.min(m, r.level), Infinity);
            return matched.map((r) => ({ node: r.node, level: r.level - (Number.isFinite(min) ? min : 0) }));
        }
        return this.buildVisible(this.treeRoots(), 0);
    });

    /** Rows currently rendered in the panel (list or tree) — drives grow-only reposition. */
    readonly visibleRowCount = computed<number>(() =>
        this.mode() === 'tree' ? this.visibleTree().length : this.filteredItems().length
    );

    isNodeChecked(node: RuntimeTreeNode): boolean {
        if (node.type === 'file') return this.activeSet().has(node.id);
        if (this.activeFolderIds().has(node.id)) return true;
        const files = this.collectDescendantFileIds(node);
        if (files.length === 0) return false;
        const sel = this.activeSet();
        return files.every((id) => sel.has(id));
    }

    isNodeIndeterminate(node: RuntimeTreeNode): boolean {
        if (node.type !== 'folder') return false;
        if (this.activeFolderIds().has(node.id)) return false;
        const files = this.collectDescendantFileIds(node);
        if (files.length === 0) return false;
        const sel = this.activeSet();
        const matched = files.filter((id) => sel.has(id)).length;
        return matched > 0 && matched < files.length;
    }

    onTreeRowClick(node: RuntimeTreeNode): void {
        if (node.disabled) return;
        if (node.type === 'folder') {
            if (this.selectionMode() === 'single') {
                this.toggleExpandNode(node);
            } else {
                this.toggleNode(node);
            }
            return;
        }
        if (this.selectionMode() === 'single') {
            this.selected.set([node.id]);
            this.selectionChange.emit([node.id]);
            this.close();
        } else {
            this.toggleNode(node);
        }
    }

    toggleExpand(event: Event, node: RuntimeTreeNode): void {
        event.stopPropagation();
        this.toggleExpandNode(node);
    }

    private toggleExpandNode(node: RuntimeTreeNode): void {
        if (node.isExpanded) {
            node.isExpanded = false;
            this.treeRoots.update((t) => [...t]);
            return;
        }
        node.isExpanded = true;
        const load = this.loadChildren();
        if (load && !node.isLoaded && (node.hasChildren ?? node.children.length > 0)) {
            this.loadLevel(node);
        }
        this.treeRoots.update((t) => [...t]);
    }

    /** Multiple-mode toggle: mutates draft + draftFolderIds (committed on Save). */
    private toggleNode(node: RuntimeTreeNode): void {
        if (node.type === 'file') {
            const has = this.draftSet().has(node.id);
            this.draft.set(has ? this.draft().filter((v) => v !== node.id) : [...this.draft(), node.id]);
            if (has) this.clearAncestorFolderFlags(node.id);
            return;
        }

        this.ensureLoaded(node, () => {
            const checked = this.isNodeChecked(node);
            const descendants = this.collectDescendantFileIds(node);

            this.draftFolderIds.update((set) => {
                const next = new Set(set);
                checked ? next.delete(node.id) : next.add(node.id);
                return next;
            });

            if (descendants.length > 0) {
                const sel = new Set(this.draft());
                if (checked) {
                    for (const id of descendants) sel.delete(id);
                } else {
                    for (const id of descendants) sel.add(id);
                }
                this.draft.set([...sel]);
            }

            if (checked) this.clearAncestorFolderFlags(node.id);
        });
    }

    private clearAncestorFolderFlags(id: string | number): void {
        const parents = this.parentById();
        const ancestors = new Set<string | number>();
        let cur = parents.get(id) ?? null;
        while (cur != null) {
            ancestors.add(cur);
            cur = parents.get(cur) ?? null;
        }
        if (ancestors.size === 0) return;
        this.draftFolderIds.update((set) => {
            let changed = false;
            const next = new Set(set);
            for (const a of ancestors) if (next.delete(a)) changed = true;
            return changed ? next : set;
        });
    }

    private activeFolderIds(): Set<string | number> {
        return this.selectionMode() === 'multiple' ? this.draftFolderIds() : new Set();
    }

    // ---- lazy load ----
    private ensureLoaded(node: RuntimeTreeNode, done: () => void): void {
        const load = this.loadChildren();
        if (!load || node.type !== 'folder' || node.isLoaded || !(node.hasChildren ?? node.children.length > 0)) {
            done();
            return;
        }
        this.loadLevel(node, () => {
            const folders = node.children.filter(
                (c) => c.type === 'folder' && (c.hasChildren ?? c.children.length > 0)
            );
            if (folders.length === 0) {
                done();
                return;
            }
            let remaining = folders.length;
            for (const f of folders) {
                this.ensureLoaded(f, () => {
                    if (--remaining === 0) done();
                });
            }
        });
    }

    private loadLevel(node: RuntimeTreeNode, onDone?: () => void): void {
        const load = this.loadChildren();
        if (!load) {
            onDone?.();
            return;
        }
        node.isLoading = true;
        load(node)
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe({
                next: (children) => {
                    node.children = children.map((c) => this.cloneNode(c));
                    node.isLoaded = true;
                    node.isLoading = false;
                    node.hasChildren = node.children.length > 0;
                    this.rebuildParentMap(this.treeRoots());
                    this.treeRoots.update((t) => [...t]);
                    onDone?.();
                },
                error: () => {
                    node.isLoading = false;
                    node.isLoaded = true;
                    this.treeRoots.update((t) => [...t]);
                    onDone?.();
                },
            });
    }

    // ---- tree helpers ----
    private cloneNode(n: SelectDropdownTreeNode): RuntimeTreeNode {
        return {
            ...n,
            isExpanded: false,
            isLoading: false,
            isLoaded: !!n.children,
            children: (n.children ?? []).map((c) => this.cloneNode(c)),
        };
    }

    private rebuildParentMap(roots: RuntimeTreeNode[]): void {
        const map = new Map<string | number, string | number | null>();
        const walk = (nodes: RuntimeTreeNode[], parent: string | number | null): void => {
            for (const n of nodes) {
                map.set(n.id, parent);
                if (n.children.length) walk(n.children, n.id);
            }
        };
        walk(roots, null);
        this.parentById.set(map);
    }

    private collectDescendantFileIds(node: RuntimeTreeNode): (string | number)[] {
        const out: (string | number)[] = [];
        const walk = (n: RuntimeTreeNode): void => {
            if (n.type === 'file') {
                out.push(n.id);
                return;
            }
            for (const c of n.children) walk(c);
        };
        for (const c of node.children) walk(c);
        return out;
    }

    private buildVisible(nodes: RuntimeTreeNode[], level: number): VisibleRow[] {
        const out: VisibleRow[] = [];
        for (const n of nodes) {
            out.push({ node: n, level });
            if (n.isExpanded && n.children.length) out.push(...this.buildVisible(n.children, level + 1));
        }
        return out;
    }

    private flattenAll(nodes: RuntimeTreeNode[], level: number): VisibleRow[] {
        const out: VisibleRow[] = [];
        for (const n of nodes) {
            out.push({ node: n, level });
            if (n.children.length) out.push(...this.flattenAll(n.children, level + 1));
        }
        return out;
    }

    onSearchInput(value: string): void {
        this.search.set(value);
    }

    itemTrackBy(_i: number, item: SelectDropdownListItem): unknown {
        return item.value;
    }

    rowTrackBy(_i: number, row: VisibleRow): string | number {
        return row.node.id;
    }
}
