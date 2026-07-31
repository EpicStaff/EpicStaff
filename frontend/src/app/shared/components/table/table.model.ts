import { SelectItem } from '../select/select.component';

export type TableRow = Record<string, unknown>;

export interface AppTableColumnDef {
    /** Unique column identifier - must match the [appTableCell] directive key */
    key: string;
    /** Header label text */
    label?: string;
    /** CSS grid column width, e.g. '1fr', '200px', 'auto', '2rem' */
    width?: string;
    /** If provided, renders a multi-select filter icon in the header */
    filterItems?: SelectItem[];
    /** If provided (and filterItems isn't), renders this app-svg-icon next to the header label */
    headerIcon?: string;
    /** Highlights the header label + icon (e.g. while an external filter driven by headerIconClick is active) */
    headerIconActive?: boolean;
    /** If > 0, renders an "(N)" badge next to the header label (e.g. active filter count) */
    headerBadgeCount?: number;
    /** Alignment of header label. Defaults to 'start' */
    align?: 'start' | 'center' | 'end';
}
