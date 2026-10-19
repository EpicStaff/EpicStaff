import { CustomShortcutEntry, ShortcutSettings } from '@shared/models';

import { EDITOR_ACTIONS, EditorAction, EditorActionId } from './editor-actions';
import { checkUserChord, ChordRejection, KeyChord } from './key-chord.util';

export type ChordSource = 'default' | 'custom';

export interface ChordHolder {
    readonly action: EditorActionId;
    readonly source: ChordSource;
    readonly customShortcutId: string | null;
}

export interface CustomShortcutRow {
    readonly id: string;
    readonly action: string;
    readonly chord: KeyChord | null;
}

export interface CustomShortcut extends CustomShortcutRow {
    readonly action: EditorActionId;
}

export interface ResolvedShortcuts {
    readonly bindings: ReadonlyMap<EditorActionId, readonly KeyChord[]>;
    readonly builtInBindings: ReadonlyMap<EditorActionId, readonly KeyChord[]>;
    readonly customShortcuts: readonly CustomShortcut[];
    readonly unboundIds: ReadonlySet<EditorActionId>;
    readonly holders: ReadonlyMap<KeyChord, ChordHolder>;
    readonly defaultsResetClearCount: number;
}

export type ShortcutChange =
    | {
          readonly kind: 'add-custom';
          readonly id: string;
          readonly action: EditorActionId;
          readonly chord: KeyChord | null;
      }
    | {
          readonly kind: 'update-custom';
          readonly id: string;
          readonly action: EditorActionId;
          readonly chord: KeyChord | null;
      }
    | { readonly kind: 'remove-custom'; readonly id: string }
    | { readonly kind: 'reset-to-defaults' };

export type ShortcutRejection = ChordRejection | 'missing' | 'limit';

export interface ShortcutRejected {
    readonly accepted: false;
    readonly rejection: ShortcutRejection;
    readonly takenBy: ChordHolder | null;
}

export interface ShortcutAccepted {
    readonly accepted: true;
    readonly displaces: EditorActionId | null;
}

export type ShortcutCheck = ShortcutRejected | ShortcutAccepted;

export type ShortcutChangeResult = ShortcutRejected | (ShortcutAccepted & { readonly rows: readonly CustomShortcut[] });

const SHORTCUTS_MAX_CUSTOM_ENTRIES = 100;

const MISSING_CUSTOM_SHORTCUT: ShortcutRejected = { accepted: false, rejection: 'missing', takenBy: null };

const ACTIONS_BY_ID: ReadonlyMap<string, EditorAction> = new Map<string, EditorAction>(
    EDITOR_ACTIONS.map((action) => [action.id, action])
);

const NODE_DEFAULT_CHORDS: ReadonlySet<KeyChord> = new Set(
    EDITOR_ACTIONS.filter(isNodeAction).flatMap((action) => action.defaultChords)
);

const EDITOR_DEFAULT_CHORDS: ReadonlySet<KeyChord> = new Set(
    EDITOR_ACTIONS.filter((action) => !isNodeAction(action)).flatMap((action) => action.defaultChords)
);

export function readCustomEntries(settings: unknown): readonly CustomShortcutEntry[] {
    const custom = isRecord(settings) ? settings['custom'] : undefined;
    return Array.isArray(custom) ? custom.filter(isCustomShortcutEntry) : [];
}

export function identifyRows(
    entries: readonly CustomShortcutEntry[],
    previousRows: readonly CustomShortcutRow[],
    createId: () => string
): CustomShortcutRow[] {
    const unclaimed = [...previousRows];
    return entries.map((entry) => {
        const index = unclaimed.findIndex((row) => row.action === entry.action && row.chord === entry.keys);
        const id = index === -1 ? createId() : unclaimed.splice(index, 1)[0].id;
        return { id, action: entry.action, chord: entry.keys };
    });
}

export function toShortcutSettings(rows: readonly CustomShortcutRow[]): ShortcutSettings {
    return { custom: rows.map((row) => ({ action: row.action, keys: row.chord })) };
}

export function haveSameEntries(entries: readonly CustomShortcutEntry[], rows: readonly CustomShortcutRow[]): boolean {
    return (
        entries.length === rows.length &&
        entries.every((entry, index) => entry.action === rows[index].action && entry.keys === rows[index].chord)
    );
}

export function resolveShortcuts(rows: readonly CustomShortcutRow[]): ResolvedShortcuts {
    const customHolders = new Map<KeyChord, ChordHolder>();
    const customShortcuts: CustomShortcut[] = [];
    for (const row of rows) {
        const action = ACTIONS_BY_ID.get(row.action);
        if (!action?.customizable) {
            continue;
        }
        const usable =
            row.chord !== null &&
            chordRejection(row.chord) === null &&
            !action.defaultChords.includes(row.chord) &&
            !customHolders.has(row.chord);
        if (usable) {
            customHolders.set(row.chord, { action: action.id, source: 'custom', customShortcutId: row.id });
        }
        customShortcuts.push({ id: row.id, action: action.id, chord: usable ? row.chord : null });
    }

    const bindings = new Map<EditorActionId, readonly KeyChord[]>();
    const builtInBindings = new Map<EditorActionId, readonly KeyChord[]>();
    const unboundIds = new Set<EditorActionId>();
    const holders = new Map<KeyChord, ChordHolder>(customHolders);
    for (const action of EDITOR_ACTIONS) {
        const builtIn = action.defaultChords.filter((chord) => !customHolders.has(chord));
        builtIn.forEach((chord) =>
            holders.set(chord, { action: action.id, source: 'default', customShortcutId: null })
        );
        builtInBindings.set(action.id, builtIn);
        bindings.set(action.id, [
            ...builtIn,
            ...customShortcuts.flatMap((shortcut) =>
                shortcut.action === action.id && shortcut.chord !== null ? [shortcut.chord] : []
            ),
        ]);
        if (action.defaultChords.length > 0 && builtIn.length === 0) {
            unboundIds.add(action.id);
        }
    }

    return {
        bindings,
        builtInBindings,
        customShortcuts,
        unboundIds,
        holders,
        defaultsResetClearCount: customShortcuts.filter(holdsNodeDefault).length,
    };
}

export function applyShortcutChange(rows: readonly CustomShortcutRow[], change: ShortcutChange): ShortcutChangeResult {
    const current = resolveShortcuts(rows);
    const kept = current.customShortcuts;
    switch (change.kind) {
        case 'add-custom': {
            const action = requireCustomizable(change.action);
            if (kept.length >= SHORTCUTS_MAX_CUSTOM_ENTRIES) {
                return { accepted: false, rejection: 'limit', takenBy: null };
            }
            const next = [...kept, { id: change.id, action: action.id, chord: change.chord }];
            return evaluateChange(current, kept, next, action.id, change.chord);
        }
        case 'update-custom': {
            const action = requireCustomizable(change.action);
            if (!kept.some((row) => row.id === change.id)) {
                return MISSING_CUSTOM_SHORTCUT;
            }
            const others = kept.filter((row) => row.id !== change.id);
            const next = kept.map((row) =>
                row.id === change.id ? { id: row.id, action: action.id, chord: change.chord } : row
            );
            return evaluateChange(current, others, next, action.id, change.chord);
        }
        case 'remove-custom': {
            if (!kept.some((row) => row.id === change.id)) {
                return MISSING_CUSTOM_SHORTCUT;
            }
            return { accepted: true, displaces: null, rows: kept.filter((row) => row.id !== change.id) };
        }
        case 'reset-to-defaults': {
            const next = kept.map((row) => (holdsNodeDefault(row) ? { ...row, chord: null } : row));
            return { accepted: true, displaces: null, rows: next };
        }
    }
}

function evaluateChange(
    current: ResolvedShortcuts,
    withoutTarget: readonly CustomShortcutRow[],
    next: readonly CustomShortcut[],
    actionId: EditorActionId,
    chord: KeyChord | null
): ShortcutChangeResult {
    if (chord === null) {
        return { accepted: true, displaces: null, rows: next };
    }

    const rejection = chordRejection(chord);
    const editorDefaultHolder = current.holders.get(chord);
    if (rejection === 'reserved' && editorDefaultHolder?.action === actionId) {
        return { accepted: false, rejection: 'taken', takenBy: editorDefaultHolder };
    }
    if (rejection !== null) {
        return { accepted: false, rejection, takenBy: null };
    }

    const holder = resolveShortcuts(withoutTarget).holders.get(chord);
    if (holder && (holder.source === 'custom' || holder.action === actionId)) {
        return { accepted: false, rejection: 'taken', takenBy: holder };
    }

    const previousHolder = current.holders.get(chord);
    const displaces =
        previousHolder?.source === 'default' && previousHolder.action !== actionId ? previousHolder.action : null;
    return { accepted: true, displaces, rows: next };
}

function chordRejection(chord: KeyChord): ChordRejection | null {
    const rejection = checkUserChord(chord);
    if (rejection === 'invalid' || rejection === 'mac-ctrl') {
        return rejection;
    }
    return EDITOR_DEFAULT_CHORDS.has(chord) ? 'reserved' : rejection;
}

function holdsNodeDefault(row: CustomShortcutRow): boolean {
    return row.chord !== null && NODE_DEFAULT_CHORDS.has(row.chord);
}

function isNodeAction(action: EditorAction): boolean {
    return action.nodeType !== undefined;
}

function requireCustomizable(actionId: EditorActionId): EditorAction {
    const action = ACTIONS_BY_ID.get(actionId);
    if (!action?.customizable) {
        throw new Error(`Shortcut action "${actionId}" cannot have custom keys`);
    }
    return action;
}

function isRecord(value: unknown): value is Readonly<Record<string, unknown>> {
    return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function isCustomShortcutEntry(value: unknown): value is CustomShortcutEntry {
    return (
        isRecord(value) &&
        typeof value['action'] === 'string' &&
        (typeof value['keys'] === 'string' || value['keys'] === null)
    );
}
