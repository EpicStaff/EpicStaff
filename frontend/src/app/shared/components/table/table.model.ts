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
    /** If provided, renders a multi-select filter icon in the header */
    filterItems?: SelectItem[];
    /** Alignment of header label. Defaults to 'start' */
    align?: 'start' | 'center' | 'end';
    /**
     * If provided, the table auto-renders a row of icon buttons for this column.
     * An `<ng-template appTableCell="…">` for the same column key still takes precedence.
     */
    actions?: AppTableRowAction[];
}
