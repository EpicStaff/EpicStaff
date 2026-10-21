import { ActionCode } from '@shared/models';

/** A row of the permission matrix: a catalog resource type, or a row an extension adds. */
export interface PermissionMatrixRow {
    /** A cell's selection key is `<code>:<action>`. */
    code: string;
    label: string;
    description: string;
    /** A same-origin image shown next to the label, or `null`. */
    iconUrl: string | null;
    /** The actions with a cell; every other column shows a dash. */
    actions: readonly ActionCode[];
    /** A cell's tooltip, by action; catalog rows have none. */
    actionDescriptions: Readonly<Partial<Record<ActionCode, string>>>;
    /** The cells (selection keys) each action needs to work, by action. */
    recommendedWith: Readonly<Partial<Record<ActionCode, readonly string[]>>>;
}

/** A collapsible group of matrix rows. */
export interface PermissionMatrixGroup {
    key: string;
    label: string;
    /** A sprite icon (`app-svg-icon`), or `null` when the group uses `iconClass`. */
    icon: string | null;
    /** The CSS class of an icon-font glyph, or `null` when the group uses `icon`. */
    iconClass: string | null;
    rows: PermissionMatrixRow[];
}
