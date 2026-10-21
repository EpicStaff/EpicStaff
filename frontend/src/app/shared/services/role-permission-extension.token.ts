import { InjectionToken } from '@angular/core';
import { ActionCode } from '@shared/models';
import { Observable } from 'rxjs';

/** One cell of an extension row: an action the row offers. */
export interface RolePermissionExtensionAction {
    action: ActionCode;
    /** The cell's tooltip. */
    description: string;
    /** Actions of the same row this one does not work without: the matrix ticks them along with it, and clears it
     *  when one of them is cleared. */
    requires: ActionCode[];
}

/** A row an extension adds to the Roles matrix. */
export interface RolePermissionExtensionRow {
    /** Unique in the whole matrix (`plugin:weather`); a cell's selection key is `<code>:<action>`. */
    code: string;
    label: string;
    description: string;
    /** A same-origin image shown next to the label, or `null`. */
    iconUrl: string | null;
    /** The row's cells, in display order; the matrix shows a cell only for these. */
    actions: RolePermissionExtensionAction[];
    /** The actions the caller may grant in the row's organization; every other cell is disabled. */
    grantable: ActionCode[];
}

/** The actions a role holds on one extension row. */
export interface RolePermissionExtensionGrant {
    code: string;
    actions: ActionCode[];
}

/** An existing role's rows of one extension and what it holds on them. */
export interface RolePermissionExtensionRoleState {
    rows: RolePermissionExtensionRow[];
    granted: RolePermissionExtensionGrant[];
    /** `false` when the caller may only look: a built-in role, or no right to update roles in the role's organization. */
    editable: boolean;
}

/** How every call of an extension fails: `message` is ready to show as it is. */
export class RolePermissionExtensionError extends Error {
    override readonly name = 'RolePermissionExtensionError';
}

/**
 * Rows a feature adds to the Roles matrix and stores itself, next to the role. Registered as a multi provider of
 * {@link ROLE_PERMISSION_EXTENSIONS}, so the Roles matrix shows and saves them without knowing the feature.
 *
 * Every observable completes after one value and fails with a {@link RolePermissionExtensionError}.
 */
export interface RolePermissionExtension {
    /** The matrix group holding the rows; unique among the groups. */
    readonly groupKey: string;
    readonly groupLabel: string;
    /** The CSS class of the icon-font glyph in the group header, e.g. `ti ti-puzzle`. */
    readonly groupIconClass: string;
    /**
     * The line the group shows for the built-in Superadmin role instead of rows: that role holds no permissions of its
     * own (a superadmin's authority comes from the account), so it has nothing to tick here.
     */
    readonly superadminRoleNote: string;

    /** `false` while the feature is switched off: the matrix then neither calls nor shows the extension. */
    isActive(): boolean;
    /** The rows for a role about to be created in `orgId`. */
    rowsForOrg(orgId: number): Observable<RolePermissionExtensionRow[]>;
    /**
     * An existing role's rows and grants. For a custom role the role's organization decides the rows; for a built-in
     * role `orgId` picks one organization, and without it the rows of every organization the caller can read are shown.
     */
    roleState(roleId: number, orgId?: number): Observable<RolePermissionExtensionRoleState>;
    /** Replaces what the role holds on this extension's rows: a row left out of `granted` loses its actions. */
    saveRole(roleId: number, granted: RolePermissionExtensionGrant[]): Observable<RolePermissionExtensionRoleState>;
}

/** Every Roles-matrix extension; empty when no feature adds rows. */
export const ROLE_PERMISSION_EXTENSIONS = new InjectionToken<readonly RolePermissionExtension[]>(
    'ROLE_PERMISSION_EXTENSIONS'
);
