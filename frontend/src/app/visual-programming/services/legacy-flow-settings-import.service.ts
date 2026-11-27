import { effect, inject, Injectable, signal, untracked } from '@angular/core';
import { DEFAULT_USER_PREFERENCES, FlowEditorPreferences, GeneralPreferences } from '@shared/models';
import { browserTimeZone, normalizeIana } from '@shared/utils';
import { forkJoin, Observable } from 'rxjs';

import { ProfileService } from '../../services/auth/profile.service';
import { UserPreferencesService } from '../../services/auth/user-preferences.service';

/** Where the flow editor kept its settings in the browser before they moved to the account. */
export const LEGACY_FLOW_SETTINGS_KEY = 'flow-settings';

type FlowEditorKey = keyof FlowEditorPreferences;

/** The old keys and the account keys they move to, with the check a stored value has to pass. */
const LEGACY_FLOW_EDITOR_KEYS: readonly (readonly [string, FlowEditorKey, (value: unknown) => boolean])[] = [
    ['arrowColors', 'arrow_colors', isBoolean],
    ['showInputsOutputs', 'show_inputs_outputs', isBoolean],
    ['edgeStyle', 'edge_style', (value) => value === 'orthogonal' || value === 'adaptive-curve'],
    ['alwaysShowNodeNumbers', 'always_show_node_numbers', isBoolean],
    ['highlightUnusedNodes', 'highlight_unused_nodes', isBoolean],
];

/**
 * Moves the flow settings the editor used to keep in localStorage to the signed-in user's account, once.
 *
 * The values move only while the account's flow editor settings are all still the defaults: a stored section and
 * an untouched one look the same from here, so any value the user chose on the account wins over the browser's.
 * The old timezone becomes the default timezone for new schedule triggers, unless it is the browser's own zone (the
 * old code stored that whether or not the user picked it) or the account already has one. The key is removed once
 * the values are saved, or at once when there is nothing to move, so the next user of this browser never gets them.
 * A failed save keeps the key, and the move is tried again on the next load.
 */
@Injectable({ providedIn: 'root' })
export class LegacyFlowSettingsImportService {
    private readonly profileService = inject(ProfileService);
    private readonly preferences = inject(UserPreferencesService);
    private readonly accountFlowEditor = this.preferences.section('flow_editor');
    private readonly accountGeneral = this.preferences.section('general');

    private readonly started = signal(false);
    private readonly handledUserIds = new Set<number>();

    constructor() {
        effect(() => {
            if (!this.started()) return;
            const userId = this.profileService.currentUserSignal()?.id;
            if (userId === undefined || this.handledUserIds.has(userId)) return;
            this.handledUserIds.add(userId);
            untracked(() => this.importForSignedInUser());
        });
    }

    /** Moves the old settings for the signed-in user, and for any user who signs in later in this tab. */
    start(): void {
        this.started.set(true);
    }

    private importForSignedInUser(): void {
        const stored = readLegacySettings();
        if (stored === undefined) return;
        if (stored === null || !isDefault(this.accountFlowEditor())) {
            localStorage.removeItem(LEGACY_FLOW_SETTINGS_KEY);
            return;
        }

        const saves: Observable<unknown>[] = [];
        const flowEditor = legacyFlowEditorChange(stored);
        if (Object.keys(flowEditor).length > 0) {
            saves.push(this.profileService.updatePreferencesSection('flow_editor', flowEditor));
        }
        const general = this.legacyGeneralChange(stored);
        if (Object.keys(general).length > 0) {
            saves.push(this.profileService.updatePreferencesSection('general', general));
        }
        if (saves.length === 0) {
            localStorage.removeItem(LEGACY_FLOW_SETTINGS_KEY);
            return;
        }
        forkJoin(saves).subscribe({
            next: () => localStorage.removeItem(LEGACY_FLOW_SETTINGS_KEY),
            // Kept for the next load; the editor works with the account's values meanwhile.
            error: () => undefined,
        });
    }

    private legacyGeneralChange(stored: Readonly<Record<string, unknown>>): Partial<GeneralPreferences> {
        const zone = stored['timezone'];
        if (typeof zone !== 'string' || !zone || this.accountGeneral().default_timezone !== null) return {};
        const normalized = normalizeIana(zone);
        if (normalized === browserTimeZone() || !isKnownZone(normalized)) return {};
        return { default_timezone: normalized };
    }
}

/** The stored object; `undefined` when there is no key, `null` when the key holds no object. */
function readLegacySettings(): Readonly<Record<string, unknown>> | null | undefined {
    const raw = localStorage.getItem(LEGACY_FLOW_SETTINGS_KEY);
    if (raw === null) return undefined;
    try {
        const parsed: unknown = JSON.parse(raw);
        return typeof parsed === 'object' && parsed !== null && !Array.isArray(parsed)
            ? (parsed as Record<string, unknown>)
            : null;
    } catch {
        return null;
    }
}

/** The stored values that differ from the defaults, under their account keys. */
function legacyFlowEditorChange(stored: Readonly<Record<string, unknown>>): Partial<FlowEditorPreferences> {
    const change: Partial<Record<FlowEditorKey, unknown>> = {};
    for (const [legacyKey, accountKey, isValid] of LEGACY_FLOW_EDITOR_KEYS) {
        const value = stored[legacyKey];
        if (isValid(value) && value !== DEFAULT_USER_PREFERENCES.flow_editor[accountKey]) {
            change[accountKey] = value;
        }
    }
    return change as Partial<FlowEditorPreferences>;
}

function isDefault(flowEditor: FlowEditorPreferences): boolean {
    const defaults = DEFAULT_USER_PREFERENCES.flow_editor;
    return (Object.keys(defaults) as FlowEditorKey[]).every((key) => flowEditor[key] === defaults[key]);
}

function isBoolean(value: unknown): boolean {
    return typeof value === 'boolean';
}

function isKnownZone(zone: string): boolean {
    try {
        new Intl.DateTimeFormat('en', { timeZone: zone });
        return true;
    } catch {
        return false;
    }
}
