import { DatePipe, formatDate, NgTemplateOutlet } from '@angular/common';
import { Component, computed, inject, input, LOCALE_ID, model, output, viewChild } from '@angular/core';
import { MatTooltip } from '@angular/material/tooltip';
import {
    ActivateButtonComponent,
    AppSvgIconComponent,
    CheckboxComponent,
    DeleteButtonComponent,
    FetchErrorStateComponent,
    FlowNodeListComponent,
    LoadingSpinnerComponent,
    NodeListItem,
    PaginationControlsComponent,
    SelectComponent,
    SelectItem,
    SelectTriggerDirective,
} from '@shared/components';
import { TooltipOnOverflowDirective } from '@shared/directives';
import { getRelativeTime } from '@shared/utils';

import { FileSizePipe } from '../../../../shared/pipes/file-size.pipe';
import {
    RECYCLE_BIN_CONTENT_LABELS,
    RECYCLE_BIN_CONTENT_VISUALS,
} from '../../constants/recycle-bin-contents.constants';
import { RECYCLE_BIN_DATE_FORMAT } from '../../constants/recycle-bin-dates.constants';
import { RECYCLE_BIN_SHOW_ALL_LIMIT } from '../../constants/recycle-bin-sources.constants';
import {
    RecycleBinDetail,
    RecycleBinFilterOption,
    RecycleBinItem,
    RecycleBinLoadStatus,
    RecycleBinPage,
    RecycleBinSort,
    RecycleBinSortDirection,
    RecycleBinSortField,
} from '../../models/recycle-bin.model';
import { documentFormatGroup, storageFormatGroup } from '../../utils/recycle-bin-contents.util';
import { COUNT_FILTER_OPTIONS, DEFAULT_SORT, INITIAL_COLUMN_DIRECTIONS } from '../../utils/recycle-bin-query.util';
import { isExpandableItem } from '../../utils/recycle-bin-rows.util';
import { purgeDate, timeLeftLabel } from '../../utils/recycle-bin-time.util';

// Widths follow the Secrets list (name flexes, the rest 128px, actions 96px).
const NAME_COLUMN = 'minmax(200px, 1fr)';
const DATA_COLUMN = '128px';
const ACTIONS_COLUMN = '96px';
// The same width as app-table's selection column.
const CHECKBOX_COLUMN = '2rem';
/** How the backend joins the parts of a text detail (bin_contents_service.py, _collection_indexes). */
const DETAIL_PART_SEPARATOR = ' · ';

/** The bin list of one tab. Presentational: the tab decides what the buttons do. */
@Component({
    selector: 'app-recycle-bin-table',
    imports: [
        DatePipe,
        NgTemplateOutlet,
        ActivateButtonComponent,
        AppSvgIconComponent,
        CheckboxComponent,
        DeleteButtonComponent,
        FetchErrorStateComponent,
        FileSizePipe,
        FlowNodeListComponent,
        LoadingSpinnerComponent,
        MatTooltip,
        PaginationControlsComponent,
        SelectComponent,
        SelectTriggerDirective,
        TooltipOnOverflowDirective,
    ],
    templateUrl: './recycle-bin-table.component.html',
    styleUrls: ['./recycle-bin-table.component.scss'],
})
export class RecycleBinTableComponent {
    readonly items = input.required<RecycleBinItem[]>();
    readonly status = input.required<RecycleBinLoadStatus>();
    readonly canRestore = input(false);
    readonly canPurge = input(false);
    readonly pluralNoun = input.required<string>();
    readonly retentionDays = input<number | null>(null);
    /** Keys of rows with a restore or purge in flight; their buttons are disabled. */
    readonly pendingKeys = input<ReadonlySet<string>>(new Set());
    /** Paging of a paged list (Files); `null` hides the paginator. */
    readonly page = input<RecycleBinPage | null>(null);
    /** Only where rows can differ in kind (Tools, Files); see recycleBinTabShowsKind. */
    readonly showKind = input(false);
    /** A checkbox column; off when the user can neither restore nor delete. */
    readonly selectable = input(false);
    readonly selectedKeys = input<ReadonlySet<string>>(new Set());
    readonly sort = input<RecycleBinSort>(DEFAULT_SORT);
    /** Each date column's own direction: what its arrow shows, sorted by it or not. */
    readonly columnDirections =
        input<Readonly<Record<RecycleBinSortField, RecycleBinSortDirection>>>(INITIAL_COLUMN_DIRECTIONS);
    /** A search or the kind filter is narrowing the list, so an empty list means "no match", not "empty bin". */
    readonly filtered = input(false);
    /** The tab's search: an opened row's contents start filtered by it, so a match inside shows. */
    readonly searchTerm = input('');
    /** Rows whose "Show all" is loading; their button is disabled. */
    readonly loadingContentKeys = input<ReadonlySet<string>>(new Set());
    /** Title of the count column (each row's `contentsTotal`); `null` hides the column. */
    readonly countLabel = input<string | null>(null);
    /** The chosen count range of the count column's filter; `null` for all. */
    readonly countFilter = input<string | null>(null);
    /** Options of the Kind column's filter; empty hides the filter. */
    readonly kindOptions = input<RecycleBinFilterOption[]>([]);
    /** The chosen kind option's value; `null` for all. */
    readonly kindFilter = input<string | null>(null);

    readonly restoreRequested = output<RecycleBinItem>();
    readonly purgeRequested = output<RecycleBinItem>();
    readonly retryRequested = output<void>();
    readonly pageRequested = output<number>();
    readonly selectionToggled = output<RecycleBinItem>();
    /** The header checkbox: `true` selects every row shown, `false` clears the selection. */
    readonly allToggled = output<boolean>();
    readonly sortRequested = output<RecycleBinSortField>();
    readonly kindFilterChanged = output<string | null>();
    readonly countFilterChanged = output<string | null>();
    /** "Show all" on a row whose contents were capped at 100. */
    readonly showAllRequested = output<RecycleBinItem>();
    /** Keys of the expanded rows; two-way, so the tab's "Expand all" can set them. */
    readonly expandedKeys = model<ReadonlySet<string>>(new Set());

    private readonly headerCheckbox = viewChild<CheckboxComponent>('headerCheckbox');

    private readonly locale = inject(LOCALE_ID);

    protected readonly dateFormat = RECYCLE_BIN_DATE_FORMAT;

    protected readonly showActions = computed(() => this.canRestore() || this.canPurge());
    protected readonly gridTemplateColumns = computed(() =>
        [
            ...(this.selectable() ? [CHECKBOX_COLUMN] : []),
            NAME_COLUMN,
            ...(this.countLabel() ? [DATA_COLUMN] : []),
            ...(this.showKind() ? [DATA_COLUMN] : []),
            DATA_COLUMN,
            DATA_COLUMN,
            ...(this.showActions() ? [ACTIONS_COLUMN] : []),
        ].join(' ')
    );
    protected readonly emptyHint = computed(() => {
        const days = this.retentionDays();
        const noun = this.pluralNoun();
        return days === null
            ? `Deleted ${noun} stay here for a while.`
            : `Deleted ${noun} stay here for ${days} ${days === 1 ? 'day' : 'days'}.`;
    });
    protected readonly allSelected = computed(() => {
        const items = this.items();
        return items.length > 0 && items.every((item) => this.selectedKeys().has(item.key));
    });
    protected readonly someSelected = computed(
        () => !this.allSelected() && this.items().some((item) => this.selectedKeys().has(item.key))
    );
    protected readonly kindFilterItems = computed<SelectItem<string | null>[]>(() => {
        const options = this.kindOptions();
        return options.length === 0 ? [] : [{ name: 'All', value: null }, ...options];
    });
    protected readonly countFilterItems: SelectItem<string | null>[] = [
        { name: 'All', value: null },
        ...COUNT_FILTER_OPTIONS,
    ];
    protected readonly showPaginator = computed(() => {
        const page = this.page();
        return page !== null && page.totalCount > page.size;
    });

    protected readonly contentLabels = RECYCLE_BIN_CONTENT_LABELS;
    protected readonly contentVisuals = RECYCLE_BIN_CONTENT_VISUALS;
    protected readonly showAllLimit = RECYCLE_BIN_SHOW_ALL_LIMIT;

    protected isExpandable(item: RecycleBinItem): boolean {
        return isExpandableItem(item);
    }

    protected isExpanded(item: RecycleBinItem): boolean {
        return this.expandedKeys().has(item.key);
    }

    /** Flow contents are nodes, as the import modal says; the other sources hold mixed kinds. */
    protected filterPlaceholder(item: RecycleBinItem): string {
        if (item.source === 'flow') return 'Select node type';
        return this.contentFilterGroup(item) ? 'Select format' : 'Select kind';
    }

    /**
     * Folders and collections are filtered by file format (PDF, MD…; plus Folder in a folder)
     * rather than by kind, where every item would be File / Document.
     */
    protected contentFilterGroup(item: RecycleBinItem): ((content: NodeListItem) => string) | null {
        if (item.source === 'storage') return storageFormatGroup;
        return item.source === 'collection' ? documentFormatGroup : null;
    }

    /** The tab's search, for an opened row's contents, only when it matched something inside the row. */
    protected contentSearch(item: RecycleBinItem): string {
        const term = this.searchTerm().toLowerCase();
        return term && item.contents.some((content) => content.name.toLowerCase().includes(term))
            ? this.searchTerm()
            : '';
    }

    protected isLoadingContents(item: RecycleBinItem): boolean {
        return this.loadingContentKeys().has(item.key);
    }

    /** "Show all" until the row holds the most it can load; past that the list just says how many more. */
    protected canShowAll(item: RecycleBinItem): boolean {
        return item.contents.length < RECYCLE_BIN_SHOW_ALL_LIMIT;
    }

    /** Contents the backend counted but didn't send (it lists at most 100). */
    protected moreCount(item: RecycleBinItem): number {
        return Math.max(0, item.contentsTotal - item.contents.length);
    }

    protected onFilterChange(key: 'kind' | 'count', value: unknown): void {
        const chosen = typeof value === 'string' ? value : null;
        if (key === 'kind') this.kindFilterChanged.emit(chosen);
        else this.countFilterChanged.emit(chosen);
    }

    /** With anything selected the header checkbox clears the selection; with nothing, it selects every row. */
    protected onHeaderCheckboxChanged(): void {
        const selectAll = !this.allSelected() && !this.someSelected();
        // Clicking a "-" box makes the browser tick it. When that click clears the selection, `checked`
        // stays false, an unchanged binding, so the box's own state is set here (CheckboxComponent then
        // makes the native box match it).
        this.headerCheckbox()?.checked.set(selectAll);
        this.allToggled.emit(selectAll);
    }

    /** A column's own direction: each arrow moves only when its own column is clicked. */
    protected arrowDirection(field: RecycleBinSortField): RecycleBinSortDirection {
        return this.columnDirections()[field];
    }

    /** A text detail's full value, for the tooltip of a clamped line. */
    protected detailText(detail: RecycleBinDetail): string {
        return detail.format === 'text' ? detail.value : '';
    }

    /** A text detail's parts: the backend joins a list (a collection's index states) with " · ". */
    protected detailParts(detail: RecycleBinDetail): string[] {
        return detail.format === 'text' ? detail.value.split(DETAIL_PART_SEPARATOR) : [];
    }

    protected isSelected(item: RecycleBinItem): boolean {
        return this.selectedKeys().has(item.key);
    }

    protected ariaSort(field: RecycleBinSortField): 'ascending' | 'descending' | null {
        const sort = this.sort();
        if (sort.field !== field) return null;
        return sort.direction === 'asc' ? 'ascending' : 'descending';
    }

    protected isPending(item: RecycleBinItem): boolean {
        return this.pendingKeys().has(item.key);
    }

    protected toggle(item: RecycleBinItem): void {
        if (!this.isExpandable(item)) return;
        this.expandedKeys.update((keys) => {
            const next = new Set(keys);
            if (next.has(item.key)) next.delete(item.key);
            else next.add(item.key);
            return next;
        });
    }

    /** Relative, like the Secrets list's "Updated"; the full date is in the cell's tooltip. */
    protected deletedLabel(item: RecycleBinItem): string {
        return getRelativeTime(item.deletedAt);
    }

    /** "6 d 5 h", counting down; whole days from the server until the retention setting has loaded. */
    protected timeLeftLabel(item: RecycleBinItem): string {
        const retentionDays = this.retentionDays();
        if (retentionDays === null) {
            if (item.daysLeft <= 0) return 'Today';
            return item.daysLeft === 1 ? '1 day' : `${item.daysLeft} days`;
        }
        return timeLeftLabel(item.deletedAt, retentionDays);
    }

    /** The cell's tooltip: the exact purge date, like the Deleted at cell shows its full date. */
    protected purgeTitle(item: RecycleBinItem): string {
        const retentionDays = this.retentionDays();
        if (retentionDays === null) return '';
        return `Deleted for good on ${formatDate(purgeDate(item.deletedAt, retentionDays), this.dateFormat, this.locale)}`;
    }
}
