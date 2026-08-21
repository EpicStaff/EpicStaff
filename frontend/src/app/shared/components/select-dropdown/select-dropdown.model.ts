import { SelectItem } from '../select/select.component';

export type { SelectItem };

export type SelectDropdownMode = 'list' | 'tree';
export type SelectDropdownSelectionMode = 'single' | 'multiple';

/** List item with optional disabled flag (SelectItem has no `disabled`). */
export interface SelectDropdownListItem<T = unknown> extends SelectItem<T> {
    disabled?: boolean;
}

export interface SelectDropdownTreeNode {
    /** Stable selection key. Identity + ancestry come from the node graph, not a path string. */
    id: string | number;
    name: string;
    type: 'folder' | 'file';
    children?: SelectDropdownTreeNode[];
    /** Lazy hint; if omitted, inferred from children?.length. */
    hasChildren?: boolean;
    icon?: string;
    disabled?: boolean;
}

/**
 * One tab rendered inside the panel header (opt-in). When `tabs` is set on the
 * dropdown the host swaps `items`/`nodes` per active tab; the dropdown only owns
 * which tab is active.
 */
export interface SelectDropdownTab {
    id: string;
    label: string;
}

/**
 * Optional action button rendered in the panel header next to the tabs
 * (e.g. "Create custom tool"). Clicking it emits `headerActionClick` with the
 * active tab id; the host decides what to open.
 */
export interface SelectDropdownHeaderAction {
    label: string;
    icon?: string;
}
