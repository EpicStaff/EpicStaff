import { DecimalPipe, NgClass, NgTemplateOutlet } from '@angular/common';
import {
    ChangeDetectionStrategy,
    Component,
    computed,
    effect,
    input,
    output,
    signal,
    TemplateRef,
    untracked,
} from '@angular/core';
import { NODE_COLORS, NODE_ICONS, NodeType } from '@shared/models';

import { AppSvgIconComponent } from '../app-svg-icon/app-svg-icon.component';
import { SearchComponent } from '../search/search.component';
import { SelectComponent, SelectItem } from '../select/select.component';

/** Any named item with a kind. Flow nodes use NodeType values; other lists (the recycle bin) their own kinds. */
export interface NodeListItem {
    name: string;
    nodeType: string;
    /** Unique within the list when `name` + `nodeType` isn't (a tree repeats names in different branches). */
    key?: string;
    /** Nesting level in a tree, 0 at the top; indents the row. */
    depth?: number;
}

export interface FlowNodeListItem extends NodeListItem {
    nodeType: NodeType;
}

/**
 * Icon and colour for a kind that isn't a NodeType: `icon` is a Tabler `ti ti-*` class, or `svgIcon`
 * a sprite icon (app-svg-icon) when the app draws that kind with one elsewhere.
 */
export type NodeListKindVisual = { color: string } & ({ icon: string } | { svgIcon: string });

const NODE_TYPE_VALUES = new Set<string>(Object.values(NodeType));
const FALLBACK_ICON = 'ti ti-point';
const FALLBACK_COLOR = 'var(--text-secondary-60)';
/** The row's own left padding, and how much each tree level adds to it. */
const ROW_PADDING_PX = 16;
const DEPTH_INDENT_PX = 20;

function isNodeType(value: string): value is NodeType {
    return NODE_TYPE_VALUES.has(value);
}

@Component({
    selector: 'app-flow-node-list',
    imports: [AppSvgIconComponent, DecimalPipe, NgClass, NgTemplateOutlet, SearchComponent, SelectComponent],
    templateUrl: './flow-node-list.component.html',
    styleUrls: ['./flow-node-list.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class FlowNodeListComponent<T extends NodeListItem = FlowNodeListItem> {
    public readonly nodes = input.required<T[]>();
    public readonly expanded = input<boolean>(false);
    public readonly nodeTypeLabels = input.required<Partial<Record<string, string>>>();
    /** Icons for kinds that aren't NodeType values; NodeType kinds use NODE_ICONS / NODE_COLORS. */
    public readonly kindVisuals = input<Partial<Record<string, NodeListKindVisual>>>({});
    /** Items that exist but weren't sent; shown as a last "and N more" line. */
    public readonly moreCount = input<number>(0);
    public readonly emptyText = input<string>('No nodes match.');
    public readonly filterPlaceholder = input<string>('Select Node Type');
    /**
     * Groups the filter offers instead of the kinds: each item's group name (e.g. a file format).
     * `null` filters by kind, labelled through `nodeTypeLabels`.
     */
    public readonly filterGroup = input<((item: T) => string) | null>(null);
    /** No vertical margin around the list block, for hosts that space their blocks themselves. */
    public readonly flush = input<boolean>(false);
    /** Hide the filter when the items fall into fewer than two kinds or groups (it couldn't narrow anything). */
    public readonly hideSingleOptionFilter = input<boolean>(false);
    /** Hide the search when there's at most one item in all (it couldn't narrow anything). */
    public readonly hideSingleItemSearch = input<boolean>(false);
    public readonly trailingTemplate = input<TemplateRef<{ $implicit: T }> | null>(null);
    public readonly searchPlaceholder = input<string>('Search node...');
    public readonly nodeTypeFilterTransparent = input<boolean>(false);
    /** Show the kind / group filter at all (labels still come from `filterGroup`). */
    public readonly filterable = input<boolean>(true);
    /**
     * Items are a tree in depth-first order (see NodeListItem.depth): an item followed by a deeper one
     * gets a chevron, and its branch starts collapsed. A search shows every match, collapsed or not.
     */
    public readonly tree = input<boolean>(false);
    /** The search the list starts with each time it opens (a host search that matched inside it). */
    public readonly presetSearch = input<string>('');

    /** The "and N more" line becomes a "Show all" button; the host loads the rest. */
    public readonly showAll = input<boolean>(false);
    /** The most the host's "Show all" loads, so the button doesn't promise more; null for no cap. */
    public readonly showAllLimit = input<number | null>(null);
    /** The host is loading the rest: the button is disabled until it's done. */
    public readonly showAllPending = input<boolean>(false);

    public readonly rowClick = output<T>();
    public readonly showAllRequested = output<void>();

    public readonly searchTerm = signal('');
    public readonly nodeTypeFilter = signal<string | null>(null);
    /** Keys (see nodeKey) of the tree branches the user opened. */
    public readonly openBranches = signal<ReadonlySet<string>>(new Set());

    public readonly nodeTypeFilterItems = computed<SelectItem<string | null>[]>(() => {
        const items: SelectItem<string | null>[] = [{ name: 'All', value: null }];
        const group = this.filterGroup();
        if (group) {
            for (const name of new Set(this.nodes().map(group))) items.push({ name, value: name });
            return items;
        }
        const labels = this.nodeTypeLabels();
        const present = new Set(this.nodes().map((node) => node.nodeType));
        for (const type of present) {
            items.push({ name: labels[type] ?? type, value: type });
        }
        return items;
    });

    /** Hidden for a single item only while it's empty: a preset search must stay clearable. */
    public readonly showSearch = computed(
        () => !this.hideSingleItemSearch() || this.nodes().length + this.moreCount() > 1 || this.searchTerm() !== ''
    );

    /** How many "Show all" loads: everything, or the host's cap. */
    public readonly showAllCount = computed(() => {
        const total = this.nodes().length + this.moreCount();
        const limit = this.showAllLimit();
        return limit === null ? total : Math.min(total, limit);
    });

    /** A search or filter shows matches from every branch, so branches can't be opened or closed then. */
    public readonly narrowed = computed(() => this.searchTerm().trim() !== '' || this.nodeTypeFilter() !== null);

    public readonly showFilter = computed(
        () => this.filterable() && (!this.hideSingleOptionFilter() || this.nodeTypeFilterItems().length - 1 > 1)
    );

    /** Keys of the items that have children: those followed by a deeper item. */
    public readonly branchKeys = computed<ReadonlySet<string>>(() => {
        const nodes = this.nodes();
        const keys = new Set<string>();
        nodes.forEach((node, index) => {
            const next = nodes[index + 1];
            if (next && (next.depth ?? 0) > (node.depth ?? 0)) keys.add(this.nodeKey(node));
        });
        return keys;
    });

    public readonly filteredNodes = computed<T[]>(() => {
        const term = this.searchTerm().toLowerCase().trim();
        const typeFilter = this.nodeTypeFilter();
        const group = this.filterGroup();
        return this.nodes().filter((node) => {
            const matchesTerm = !term || node.name.toLowerCase().includes(term);
            const matchesType = typeFilter === null || (group ? group(node) : node.nodeType) === typeFilter;
            return matchesTerm && matchesType;
        });
    });

    /** The rows shown: the filtered items, minus the insides of closed branches while nothing narrows the list. */
    public readonly visibleNodes = computed<T[]>(() => {
        const nodes = this.filteredNodes();
        if (!this.tree() || this.narrowed()) return nodes;
        const open = this.openBranches();
        const visible: T[] = [];
        // Depth of the closed branch being skipped; null while not inside one.
        let closedDepth: number | null = null;
        for (const node of nodes) {
            const depth = node.depth ?? 0;
            if (closedDepth !== null && depth > closedDepth) continue;
            closedDepth = null;
            visible.push(node);
            if (this.branchKeys().has(this.nodeKey(node)) && !open.has(this.nodeKey(node))) closedDepth = depth;
        }
        return visible;
    });

    constructor() {
        effect(() => {
            if (this.expanded()) {
                // Read only when the list opens: a later change of the host's search mustn't wipe what
                // the user did inside an open list.
                this.searchTerm.set(untracked(() => this.presetSearch()));
                this.nodeTypeFilter.set(null);
                this.openBranches.set(new Set());
            }
        });
    }

    public nodeKey(node: T): string {
        return node.key ?? node.name + node.nodeType;
    }

    public isBranch(node: T): boolean {
        return this.tree() && !this.narrowed() && this.branchKeys().has(this.nodeKey(node));
    }

    public branchLabel(node: T): string {
        return `${this.isOpen(node) ? 'Collapse' : 'Expand'} ${node.name}`;
    }

    public isOpen(node: T): boolean {
        return this.openBranches().has(this.nodeKey(node));
    }

    public toggleBranch(node: T, event: Event): void {
        event.stopPropagation();
        this.flipBranch(node);
    }

    /** A click on a row opens or closes it when it's a tree branch (like a folder in Files). */
    public onRowClick(node: T): void {
        if (this.isBranch(node)) this.flipBranch(node);
        this.rowClick.emit(node);
    }

    public onNodeTypeFilterChange(value: unknown): void {
        this.nodeTypeFilter.set(typeof value === 'string' ? value : null);
    }

    public nodeIcon(nodeType: string): string {
        const visual = this.kindVisuals()[nodeType];
        if (visual && 'icon' in visual) return visual.icon;
        return isNodeType(nodeType) ? NODE_ICONS[nodeType] : FALLBACK_ICON;
    }

    /** The sprite icon of a kind drawn with one; `null` for a font icon. */
    public nodeSvgIcon(nodeType: string): string | null {
        const visual = this.kindVisuals()[nodeType];
        return visual && 'svgIcon' in visual ? visual.svgIcon : null;
    }

    public nodeColor(nodeType: string): string {
        return this.kindVisuals()[nodeType]?.color ?? (isNodeType(nodeType) ? NODE_COLORS[nodeType] : FALLBACK_COLOR);
    }

    public nodeTypeLabel(nodeType: string): string {
        return this.nodeTypeLabels()[nodeType] ?? nodeType;
    }

    public rowIndent(node: T): number {
        return ROW_PADDING_PX + (node.depth ?? 0) * DEPTH_INDENT_PX;
    }

    /** The label beside an item: its filter group when the list groups by one (so label and filter agree), else its kind. */
    public itemLabel(node: T): string {
        const group = this.filterGroup();
        return group ? group(node) : this.nodeTypeLabel(node.nodeType);
    }

    private flipBranch(node: T): void {
        const key = this.nodeKey(node);
        this.openBranches.update((keys) => {
            const next = new Set(keys);
            if (next.has(key)) next.delete(key);
            else next.add(key);
            return next;
        });
    }
}
