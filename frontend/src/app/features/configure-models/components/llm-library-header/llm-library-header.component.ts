import {
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
import { BulkSelectDropdownComponent, ButtonComponent, SearchComponent, SelectComponent } from '@shared/components';
import { HasPermissionDirective } from '@shared/directives';
import { ActionCode, ResourceCode } from '@shared/models';

import { LLM_LIBRARY_CAPABILITIES } from '../../constants/llm-library-capabilities.constant';
import { isLibrarySectionKey, LibrarySectionKey } from '../../models/llm-library.model';

/**
 * Design minimums while the toolbar sits beside the title, and the gaps (title to toolbar, between controls). The two
 * minimums, and the labelled Capabilities width below, reach the stylesheet as custom properties, so they are set here
 * only.
 */
const TITLE_MIN_WIDTH = 372;
const SEARCH_MIN_WIDTH = 201;
/** The labelled Capabilities filter's fixed width: what "All capabilities" takes (Figma). */
const CAPABILITIES_LABELLED_WIDTH = 157;
const HEADER_GAP = 24;
const CONTROL_GAP = 8;

/** A toolbar control (after the search) in one of its looks; the action is Add, or Delete with a selection. */
type ToolbarControlLook =
    | 'capabilities'
    | 'capabilities-icon'
    | 'select'
    | 'select-icon'
    | 'selected'
    | 'selected-icon'
    | 'add'
    | 'add-icon'
    | 'delete'
    | 'delete-icon';

/**
 * Widths of each look until it has been on screen once and measured: the icon looks are the design's fixed sizes,
 * the labelled ones estimates for Inter 14px.
 */
const ESTIMATED_CONTROL_WIDTHS: Record<ToolbarControlLook, number> = {
    capabilities: CAPABILITIES_LABELLED_WIDTH,
    'capabilities-icon': 67,
    select: 96,
    'select-icon': 40,
    selected: 177,
    'selected-icon': 131,
    add: 180,
    'add-icon': 40,
    delete: 120,
    'delete-icon': 40,
};

/**
 * Beside the title with labels; beside it icon-only; or under it (`stacked`), its second row giving up labels from
 * the end: first the action (Add or Delete) goes icon-only, then all of them.
 */
type ToolbarLayout = 'labels' | 'icons' | 'stacked' | 'stacked-action-icon' | 'stacked-icons';

interface ToolbarIcons {
    capabilities: boolean;
    select: boolean;
    action: boolean;
}

interface ToolbarControlLooks {
    capabilities: ToolbarControlLook;
    select: ToolbarControlLook;
    action: ToolbarControlLook;
}

const ALL_LABELS: ToolbarIcons = { capabilities: false, select: false, action: false };
const ALL_ICONS: ToolbarIcons = { capabilities: true, select: true, action: true };
const ACTION_ICON: ToolbarIcons = { capabilities: false, select: false, action: true };

/**
 * The LLM Library's sticky header: the title and its toolbar (search, Capabilities filter, Select, and Add
 * Configuration or, with a selection, Delete). It lays the toolbar out from its own measured width; the page owns
 * the search, the filter, select mode and the selection, and acts on what this reports.
 *
 * The Capabilities filter's value is the header's own (the select is uncontrolled): the page only hears of a change
 * through `sectionFilterChange`, and cannot set or reset the filter.
 */
@Component({
    selector: 'app-llm-library-header',
    imports: [SearchComponent, SelectComponent, BulkSelectDropdownComponent, ButtonComponent, HasPermissionDirective],
    templateUrl: './llm-library-header.component.html',
    styleUrls: ['./llm-library-header.component.scss'],
    host: {
        '[style.--llm-library-title-min-width.px]': 'titleMinWidth',
        '[style.--llm-library-search-min-width.px]': 'searchMinWidth',
        '[style.--llm-library-capabilities-width.px]': 'capabilitiesLabelledWidth',
    },
})
export class LlmLibraryHeaderComponent {
    readonly searchQuery = input('');
    readonly selectMode = input(false);
    /** How many selected items a Delete would act on. */
    readonly selectedCount = input(0);
    readonly allSelected = input(false);
    /** Whether the Select control is on the page (still subject to the delete permission). */
    readonly showSelect = input(false);
    readonly isDeleting = input(false);

    readonly searchChange = output<string>();
    /** The section the Capabilities filter shows; null shows all of them. */
    readonly sectionFilterChange = output<LibrarySectionKey | null>();
    readonly selectModeEntered = output<void>();
    /** The × of Select, or Select clicked again with nothing ticked: select mode ends, with its selection. */
    readonly selectModeExited = output<void>();
    readonly selectAllToggled = output<void>();
    /** "Clear Selection": the selection empties, select mode stays. */
    readonly selectionCleared = output<void>();
    readonly addClicked = output<void>();
    readonly deleteClicked = output<void>();

    private readonly header = viewChild<ElementRef<HTMLElement>>('header');
    private readonly capabilitiesControl = viewChild<ElementRef<HTMLElement>>('capabilitiesControl');
    private readonly selectControl = viewChild(BulkSelectDropdownComponent, { read: ElementRef });
    private readonly bulkSelect = viewChild(BulkSelectDropdownComponent);
    private readonly actionControl = viewChild<ButtonComponent, ElementRef<HTMLElement>>('actionControl', {
        read: ElementRef,
    });
    private readonly addButton = viewChild('addButton', { read: ButtonComponent });

    /** Delete replaces Add Configuration, and Select shows its count, only while something is selected. */
    protected readonly hasSelection = computed(() => this.selectedCount() > 0);
    /** Null until measured: the first frame keeps the labels in the row. */
    private readonly headerWidth = signal<number | null>(null);
    /** Natural width of each control look, taken while it was on screen; estimates until then. */
    private readonly controlWidths = signal<Partial<Record<ToolbarControlLook, number>>>({});
    /**
     * Every switch comes from the measured widths and the design's numbers: the labelled toolbar beside a title at its
     * minimum (`TITLE_MIN_WIDTH`, the search at `SEARCH_MIN_WIDTH`), else the icon-only one, else under the title
     * with as many labels as its row fits.
     */
    protected readonly toolbarLayout = computed<ToolbarLayout>(() => {
        const width = this.headerWidth();
        if (width === null) return 'labels';
        const besideTitle = width - TITLE_MIN_WIDTH - HEADER_GAP;
        if (this.toolbarRowWidth(ALL_LABELS) <= besideTitle) return 'labels';
        if (this.toolbarRowWidth(ALL_ICONS) <= besideTitle) return 'icons';
        if (this.controlsRowWidth(ALL_LABELS) <= width) return 'stacked';
        if (this.controlsRowWidth(ACTION_ICON) <= width) return 'stacked-action-icon';
        return 'stacked-icons';
    });
    protected readonly isStacked = computed(() => this.toolbarLayout().startsWith('stacked'));
    protected readonly toolbarIcons = computed<ToolbarIcons>(() => {
        switch (this.toolbarLayout()) {
            case 'icons':
            case 'stacked-icons':
                return ALL_ICONS;
            case 'stacked-action-icon':
                return ACTION_ICON;
            default:
                return ALL_LABELS;
        }
    });
    /** Beside the title, what the toolbar needs: the title gives way (to its minimum) before it does. */
    protected readonly toolbarMinWidth = computed(() =>
        this.isStacked() ? null : this.toolbarRowWidth(this.toolbarIcons())
    );

    /** The header and the toolbar controls on screen, observed as they come and go. */
    private readonly observeToolbar = effect(() => {
        const elements = [this.header(), this.capabilitiesControl(), this.selectControl(), this.actionControl()]
            .filter((element): element is ElementRef<HTMLElement> => !!element)
            .map((element) => element.nativeElement);
        untracked(() => {
            for (const element of this.observedElements) {
                if (!elements.includes(element)) this.resizeObserver?.unobserve(element);
            }
            for (const element of elements) this.resizeObserver?.observe(element);
            this.observedElements = elements;
        });
    });

    protected readonly capabilities = LLM_LIBRARY_CAPABILITIES;
    protected readonly titleMinWidth = TITLE_MIN_WIDTH;
    protected readonly searchMinWidth = SEARCH_MIN_WIDTH;
    protected readonly capabilitiesLabelledWidth = CAPABILITIES_LABELLED_WIDTH;
    protected readonly ResourceCode = ResourceCode;
    protected readonly ActionCode = ActionCode;

    private readonly destroyRef = inject(DestroyRef);
    private readonly resizeObserver =
        typeof ResizeObserver === 'undefined' ? null : new ResizeObserver((entries) => this.onResize(entries));
    private observedElements: HTMLElement[] = [];

    constructor() {
        this.destroyRef.onDestroy(() => this.resizeObserver?.disconnect());
    }

    /** Focuses Add Configuration, e.g. once the deleted card (or Delete, gone with the selection) took the focus. */
    public focusAddButton(): void {
        this.addButton()?.focus();
    }

    /** Focuses Select, where it is on the page. */
    public focusSelect(): void {
        this.bulkSelect()?.focus();
    }

    /** Whether `node` is in the Select control: a click there belongs to select mode. */
    public containsSelectControl(node: Node): boolean {
        return !!this.selectControl()?.nativeElement.contains(node);
    }

    /** The select reports an `unknown` value: only "All capabilities" (null) or a section key goes on. */
    protected onSectionFilterChange(value: unknown): void {
        if (value === null || isLibrarySectionKey(value)) this.sectionFilterChange.emit(value);
    }

    /**
     * The header's own width (not the viewport's: the sidebar and the settings layout around it do not matter), and
     * each control's natural width in the look it shows. Controls are recorded against the looks they were rendered
     * with, before a new header width can change those looks.
     */
    private onResize(entries: ResizeObserverEntry[]): void {
        const looks = this.controlLooks(this.toolbarIcons());
        const measured: Partial<Record<ToolbarControlLook, number>> = {};
        let headerWidth: number | null = null;
        for (const entry of entries) {
            const target = entry.target;
            if (target === this.header()?.nativeElement) {
                headerWidth = entry.contentRect.width;
                continue;
            }
            const width = entry.borderBoxSize?.[0]?.inlineSize ?? target.getBoundingClientRect().width;
            if (width <= 0) continue;
            if (target === this.capabilitiesControl()?.nativeElement) measured[looks.capabilities] = width;
            else if (target === this.selectControl()?.nativeElement) measured[looks.select] = width;
            else if (target === this.actionControl()?.nativeElement) measured[looks.action] = width;
        }
        if (Object.keys(measured).length > 0) this.controlWidths.update((widths) => ({ ...widths, ...measured }));
        if (headerWidth !== null) this.headerWidth.set(headerWidth);
    }

    private controlLooks(icons: ToolbarIcons): ToolbarControlLooks {
        const selection = this.hasSelection();
        const selectLook: ToolbarControlLook = selection ? 'selected' : 'select';
        const actionLook: ToolbarControlLook = selection ? 'delete' : 'add';
        return {
            capabilities: icons.capabilities ? 'capabilities-icon' : 'capabilities',
            select: icons.select ? `${selectLook}-icon` : selectLook,
            action: icons.action ? `${actionLook}-icon` : actionLook,
        } as ToolbarControlLooks;
    }

    /** The controls after the search, in the given looks, with the gaps between them; absent ones count nothing. */
    private controlsRowWidth(icons: ToolbarIcons): number {
        const looks = this.controlLooks(icons);
        const widths = this.controlWidths();
        const present: ToolbarControlLook[] = [looks.capabilities];
        if (this.selectControl()) present.push(looks.select);
        if (this.actionControl()) present.push(looks.action);
        const total = present.reduce((sum, look) => sum + (widths[look] ?? ESTIMATED_CONTROL_WIDTHS[look]), 0);
        return total + CONTROL_GAP * (present.length - 1);
    }

    /** The whole toolbar beside the title: the search at its minimum, then the controls. */
    private toolbarRowWidth(icons: ToolbarIcons): number {
        return SEARCH_MIN_WIDTH + CONTROL_GAP + this.controlsRowWidth(icons);
    }
}
