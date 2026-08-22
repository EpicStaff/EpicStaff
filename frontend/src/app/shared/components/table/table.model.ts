import { SelectItem } from '../select/select.component';

export type TableRow = Record<string, unknown>;

export type AppTableActionVariant = 'default' | 'danger' | 'warning' | 'muted';

export interface AppTableRowAction {
    /** Icon shown inside the action button (matches an `app-svg-icon` icon name). */
    icon: string;
    /** Tooltip shown on hover. Optional. */
    tooltip?: string;
    /** Visual variant. Accepts a static value or a row-dependent function. Defaults to `default`. */
    variant?: AppTableActionVariant | ((row: TableRow) => AppTableActionVariant);
    /** Return `true` to hide the action for the given row. */
    hidden?: (row: TableRow) => boolean;
    /** Return `true` to disable the action for the given row. */
    disabled?: (row: TableRow) => boolean;
    /** Click handler for the action. */
    onClick: (row: TableRow) => void;
}

export interface AppTableColumnDef {
    /** Unique column identifier - must match the [appTableCell] directive key */
    key: string;
    /** Header label text */
    label?: string;
    /** CSS grid column width, e.g. '1fr', '200px', 'auto', '2rem' */
    width?: string;
    /** If provided, renders a filter icon in the header opening a dropdown of these items. */
    filterItems?: SelectItem[];
    /** If provided (and filterItems isn't), renders this app-svg-icon next to the header label */
    headerIcon?: string;
    /** Highlights the header label + icon (e.g. while an external filter driven by headerIconClick is active) */
    headerIconActive?: boolean;
    /** If > 0, renders an "(N)" badge next to the header label (e.g. active filter count) */
    headerBadgeCount?: number;
    /**
     * Filter selection mode when `filterItems` is set.
     *  - `multi` (default): user can pick multiple values; `filterChange` emits the full array.
     *  - `single`: user picks a single value; `filterChange` emits an array with 0 or 1 items.
     */
    filterKind?: 'single' | 'multi';
    /** Show a search input inside the filter dropdown. Applies to `filterKind: 'single'` only. */
    filterSearchable?: boolean;
    /**
     * When `true`, the table emits `filterChange` but does NOT apply a client-side filter on this column —
     * the consumer is expected to refetch (or otherwise resolve) filtered data itself.
     * Defaults to `false` (built-in client-side filtering).
     */
    filterServerSide?: boolean;
    /** Alignment of header label. Defaults to 'start' */
    align?: 'start' | 'center' | 'end';
    /**
     * If provided, the table auto-renders a row of icon buttons for this column.
     * An `<ng-template appTableCell="…">` for the same column key still takes precedence.
     */
    actions?: AppTableRowAction[];
}
