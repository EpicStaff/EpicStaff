import { FullMembership } from '../role-based-access';
import { ActivePermissions } from '../role-based-access';

export interface GetMeResponse {
    id: number;
    email: string;
    display_name: string | null;
    is_superadmin: boolean;
    is_active: boolean;
    created_at: string;
    updated_at: string;
    memberships: FullMembership[];
    active_organization_id: number | null;
    active_permissions: ActivePermissions | null;
    avatar_url: string | null;
    /** Keys of the guided tours the user finished or skipped, sorted. Read-only: saved one at a time by a POST. */
    completed_tours: string[];
    custom_shortcuts: ShortcutSettings;
}

export interface ShortcutParams {
    readonly [key: string]: number | string;
}

export interface CustomShortcutEntry {
    readonly action: string;
    readonly keys: string | null;
    readonly params?: ShortcutParams;
}

export interface ActionKeyOverrides {
    readonly [action: string]: string | null;
}

export interface ShortcutSettings {
    readonly custom: readonly CustomShortcutEntry[];
    readonly overrides: ActionKeyOverrides;
}

export const EMPTY_SHORTCUT_SETTINGS: ShortcutSettings = { custom: [], overrides: {} };

export interface UpdateMeRequest {
    display_name: string;
}

export interface PasswordChangeVerifyRequest {
    current_password: string;
}

export interface PasswordChangeVerifyResponse {
    ticket: string;
    expires_in: number;
}

export interface PasswordChangeConfirmRequest {
    ticket: string;
    new_password: string;
}
