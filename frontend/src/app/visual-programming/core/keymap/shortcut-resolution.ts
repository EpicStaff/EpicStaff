import { CustomShortcutEntry, ShortcutParams, ShortcutSettings } from '@shared/models';

import { EDITOR_ACTIONS, EditorAction, EditorActionId } from './editor-actions';
import { checkUserChord, ChordRejection, KeyChord } from './key-chord.util';
import { isShortcutParams, readActionParams, sameParams } from './shortcut-params';

export type ChordSource = 'default' | 'override' | 'custom';

export interface ChordHolder {
    readonly action: EditorActionId;
    readonly source: ChordSource;
    readonly customShortcutId: string | null;
    readonly params?: ShortcutParams;
}

export interface CustomShortcutRow {
    readonly id: string;
    readonly action: string;
    readonly chord: KeyChord | null;
    readonly params?: ShortcutParams;
}

export interface CustomShortcut extends CustomShortcutRow {
    readonly action: EditorActionId;
}

export type KeyOverrides = ReadonlyMap<string, KeyChord | null>;

export interface ResolvedShortcuts {
    readonly bindings: ReadonlyMap<EditorActionId, readonly KeyChord[]>;
    readonly builtInBindings: ReadonlyMap<EditorActionId, readonly KeyChord[]>;
    readonly customShortcuts: readonly CustomShortcut[];
    readonly overrides: ReadonlyMap<EditorActionId, KeyChord | null>;
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
          readonly params?: ShortcutParams;
      }
    | {
          readonly kind: 'update-custom';
          readonly id: string;
          readonly action: EditorActionId;
          readonly chord: KeyChord | null;
          readonly params?: ShortcutParams;
      }
    | { readonly kind: 'remove-custom'; readonly id: string }
    | { readonly kind: 'set-node-key'; readonly action: EditorActionId; readonly chord: KeyChord | null }
    | { readonly kind: 'reset-node-key'; readonly action: EditorActionId }
    | { readonly kind: 'reset-to-defaults' };

export type ShortcutRejection = ChordRejection | 'missing' | 'limit' | 'params';

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

export type ShortcutChangeResult =
    | ShortcutRejected
    | (ShortcutAccepted & {
          readonly rows: readonly CustomShortcut[];
          readonly overrides: ReadonlyMap<EditorActionId, KeyChord | null>;
      });

const SHORTCUTS_MAX_CUSTOM_ENTRIES = 100;

const NO_OVERRIDES: KeyOverrides = new Map();

const MISSING_CUSTOM_SHORTCUT: ShortcutRejected = { accepted: false, rejection: 'missing', takenBy: null };

const MISSING_PARAMS: ShortcutRejected = { accepted: false, rejection: 'params', takenBy: null };

const ACTIONS_BY_ID: ReadonlyMap<string, EditorAction> = new Map<string, EditorAction>(
    EDITOR_ACTIONS.map((action) => [action.id, action])
);

const NODE_DEFAULT_CHORDS: ReadonlySet<KeyChord> = new Set(
    EDITOR_ACTIONS.filter(isNodeAction).flatMap((action) => action.defaultChords)
);

const EDITOR_DEFAULT_CHORDS: ReadonlySet<KeyChord> = new Set(
    EDITOR_ACTIONS.filter((action) => !isNodeAction(action)).flatMap((action) => action.defaultChords)
);

export function isNodeKeyEditable(actionId: string): boolean {
    const action = ACTIONS_BY_ID.get(actionId);
    return action !== undefined && isOverridable(action);
}

export function readCustomEntries(settings: unknown): readonly CustomShortcutEntry[] {
    const custom = isRecord(settings) ? settings['custom'] : undefined;
    return Array.isArray(custom) ? custom.flatMap(readCustomEntry) : [];
}

export function readKeyOverrides(settings: unknown): KeyOverrides {
    const overrides = isRecord(settings) ? settings['overrides'] : undefined;
    if (!isRecord(overrides)) {
        return NO_OVERRIDES;
    }
    return new Map(
        Object.entries(overrides).flatMap(([action, chord]) =>
            typeof chord === 'string' || chord === null ? [[action, chord] as const] : []
        )
    );
}

export function identifyRows(
    entries: readonly CustomShortcutEntry[],
    previousRows: readonly CustomShortcutRow[],
    createId: () => string
): CustomShortcutRow[] {
    const unclaimed = [...previousRows];
    return entries.map((entry) => {
        const index = unclaimed.findIndex((row) => isSameEntry(entry, row));
        const id = index === -1 ? createId() : unclaimed.splice(index, 1)[0].id;
        return withParams({ id, action: entry.action, chord: entry.keys }, entry.params);
    });
}

export function toShortcutSettings(
    rows: readonly CustomShortcutRow[],
    overrides: KeyOverrides = NO_OVERRIDES
): ShortcutSettings {
    return {
        custom: rows.map((row) =>
            row.params === undefined || Object.keys(row.params).length === 0
                ? { action: row.action, keys: row.chord }
                : { action: row.action, keys: row.chord, params: row.params }
        ),
        overrides: Object.fromEntries(overrides),
    };
}

export function haveSameEntries(entries: readonly CustomShortcutEntry[], rows: readonly CustomShortcutRow[]): boolean {
    return entries.length === rows.length && entries.every((entry, index) => isSameEntry(entry, rows[index]));
}

export function haveSameOverrides(first: KeyOverrides, second: KeyOverrides): boolean {
    return (
        first.size === second.size &&
        [...first].every(([action, chord]) => second.has(action) && second.get(action) === chord)
    );
}

export function resolveShortcuts(
    rows: readonly CustomShortcutRow[],
    storedOverrides: KeyOverrides = NO_OVERRIDES
): ResolvedShortcuts {
    const customHolders = new Map<KeyChord, ChordHolder>();
    const customShortcuts: CustomShortcut[] = [];
    for (const row of rows) {
        const action = ACTIONS_BY_ID.get(row.action);
        if (!action?.customizable) {
            continue;
        }
        const params = paramsOf(action, row.params);
        const usable =
            row.chord !== null &&
            params !== null &&
            chordRejection(row.chord) === null &&
            !action.defaultChords.includes(row.chord) &&
            !customHolders.has(row.chord);
        if (usable) {
            customHolders.set(
                row.chord,
                withParams({ action: action.id, source: 'custom', customShortcutId: row.id }, params)
            );
        }
        customShortcuts.push(withParams({ id: row.id, action: action.id, chord: usable ? row.chord : null }, params));
    }

    const overrides = new Map<EditorActionId, KeyChord | null>();
    const overrideHolders = new Map<KeyChord, ChordHolder>();
    for (const action of EDITOR_ACTIONS as readonly EditorAction<EditorActionId>[]) {
        if (!isOverridable(action) || !storedOverrides.has(action.id)) {
            continue;
        }
        const chord = storedOverrides.get(action.id) ?? null;
        if (chord !== null && (action.defaultChords.includes(chord) || chordRejection(chord) !== null)) {
            continue;
        }
        if (chord !== null && overrideHolders.has(chord)) {
            continue;
        }
        const held = chord !== null && !customHolders.has(chord) ? chord : null;
        overrides.set(action.id, held);
        if (held !== null) {
            overrideHolders.set(held, { action: action.id, source: 'override', customShortcutId: null });
        }
    }

    const bindings = new Map<EditorActionId, readonly KeyChord[]>();
    const builtInBindings = new Map<EditorActionId, readonly KeyChord[]>();
    const unboundIds = new Set<EditorActionId>();
    const holders = new Map<KeyChord, ChordHolder>([...customHolders, ...overrideHolders]);
    for (const action of EDITOR_ACTIONS) {
        const builtIn = overrides.has(action.id)
            ? overrideChords(overrides.get(action.id) ?? null)
            : action.defaultChords.filter((chord) => !customHolders.has(chord) && !overrideHolders.has(chord));
        builtIn
            .filter((chord) => !holders.has(chord))
            .forEach((chord) => holders.set(chord, { action: action.id, source: 'default', customShortcutId: null }));
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
        overrides,
        unboundIds,
        holders,
        defaultsResetClearCount: customShortcuts.filter(holdsNodeDefault).length,
    };
}

export function applyShortcutChange(
    rows: readonly CustomShortcutRow[],
    change: ShortcutChange,
    storedOverrides: KeyOverrides = NO_OVERRIDES
): ShortcutChangeResult {
    const current = resolveShortcuts(rows, storedOverrides);
    const kept = current.customShortcuts;
    const overrides = current.overrides;
    switch (change.kind) {
        case 'add-custom': {
            const action = requireCustomizable(change.action);
            if (kept.length >= SHORTCUTS_MAX_CUSTOM_ENTRIES) {
                return { accepted: false, rejection: 'limit', takenBy: null };
            }
            const params = paramsOf(action, change.params);
            const next = [...kept, withParams({ id: change.id, action: action.id, chord: change.chord }, params)];
            return evaluateCustomChange(current, kept, next, action.id, change.chord, params !== null);
        }
        case 'update-custom': {
            const action = requireCustomizable(change.action);
            if (!kept.some((row) => row.id === change.id)) {
                return MISSING_CUSTOM_SHORTCUT;
            }
            const params = paramsOf(action, change.params);
            const others = kept.filter((row) => row.id !== change.id);
            const next = kept.map((row) =>
                row.id === change.id ? withParams({ id: row.id, action: action.id, chord: change.chord }, params) : row
            );
            return evaluateCustomChange(current, others, next, action.id, change.chord, params !== null);
        }
        case 'remove-custom': {
            if (!kept.some((row) => row.id === change.id)) {
                return MISSING_CUSTOM_SHORTCUT;
            }
            return { accepted: true, displaces: null, rows: kept.filter((row) => row.id !== change.id), overrides };
        }
        case 'set-node-key':
            return evaluateNodeKeyChange(current, requireOverridable(change.action), change.chord);
        case 'reset-node-key': {
            const action = requireOverridable(change.action);
            return evaluateNodeKeyChange(current, action, action.defaultChords[0] ?? null);
        }
        case 'reset-to-defaults': {
            const next = kept.map((row) => (holdsNodeDefault(row) ? { ...row, chord: null } : row));
            return { accepted: true, displaces: null, rows: next, overrides: new Map() };
        }
    }
}

function evaluateCustomChange(
    current: ResolvedShortcuts,
    withoutTarget: readonly CustomShortcutRow[],
    next: readonly CustomShortcut[],
    actionId: EditorActionId,
    chord: KeyChord | null,
    hasRequiredParams: boolean
): ShortcutChangeResult {
    if (chord === null) {
        return hasRequiredParams
            ? { accepted: true, displaces: null, rows: next, overrides: current.overrides }
            : MISSING_PARAMS;
    }

    const rejection = chordRejection(chord);
    const editorDefaultHolder = current.holders.get(chord);
    if (rejection === 'reserved' && editorDefaultHolder?.action === actionId) {
        return { accepted: false, rejection: 'taken', takenBy: editorDefaultHolder };
    }
    if (rejection !== null) {
        return { accepted: false, rejection, takenBy: null };
    }

    const holder = resolveShortcuts(withoutTarget, current.overrides).holders.get(chord);
    if (holder && (holder.source === 'custom' || holder.action === actionId)) {
        return { accepted: false, rejection: 'taken', takenBy: holder };
    }

    if (!hasRequiredParams) {
        return MISSING_PARAMS;
    }

    const previousHolder = current.holders.get(chord);
    const displaced =
        previousHolder?.source !== 'custom' && previousHolder?.action !== actionId ? previousHolder : undefined;
    return {
        accepted: true,
        displaces: displaced?.action ?? null,
        rows: next,
        overrides:
            displaced?.source === 'override'
                ? withOverride(current.overrides, displaced.action, null)
                : current.overrides,
    };
}

function evaluateNodeKeyChange(
    current: ResolvedShortcuts,
    action: EditorAction,
    chord: KeyChord | null
): ShortcutChangeResult {
    const rows = current.customShortcuts;
    const isOwnDefault = chord !== null && action.defaultChords.includes(chord);
    const withoutOwn = withoutOverride(current.overrides, action.id);
    const nextOwn = isOwnDefault ? withoutOwn : withOverride(withoutOwn, action.id, chord);
    if (chord === null) {
        return { accepted: true, displaces: null, rows, overrides: nextOwn };
    }

    const rejection = chordRejection(chord);
    if (rejection !== null) {
        return { accepted: false, rejection, takenBy: null };
    }

    const holder = resolveShortcuts(rows, withOverride(withoutOwn, action.id, null)).holders.get(chord);
    if (holder?.source === 'custom' || (isOwnDefault && holder !== undefined && holder.action !== action.id)) {
        return { accepted: false, rejection: 'taken', takenBy: holder ?? null };
    }
    const displaces = holder && holder.action !== action.id ? holder.action : null;
    return {
        accepted: true,
        displaces,
        rows,
        overrides: holder?.source === 'override' ? withOverride(nextOwn, holder.action, null) : nextOwn,
    };
}

function withOverride(
    overrides: ReadonlyMap<EditorActionId, KeyChord | null>,
    actionId: EditorActionId,
    chord: KeyChord | null
): ReadonlyMap<EditorActionId, KeyChord | null> {
    return new Map(overrides).set(actionId, chord);
}

function withoutOverride(
    overrides: ReadonlyMap<EditorActionId, KeyChord | null>,
    actionId: EditorActionId
): ReadonlyMap<EditorActionId, KeyChord | null> {
    const next = new Map(overrides);
    next.delete(actionId);
    return next;
}

function overrideChords(chord: KeyChord | null): readonly KeyChord[] {
    return chord === null ? [] : [chord];
}

function paramsOf(action: EditorAction, params: ShortcutParams | undefined): ShortcutParams | undefined | null {
    return action.param === undefined ? undefined : readActionParams(action.param, params);
}

function withParams<T extends object>(value: T, params: ShortcutParams | undefined | null): T {
    return params ? { ...value, params } : value;
}

function isSameEntry(entry: CustomShortcutEntry, row: CustomShortcutRow): boolean {
    return entry.action === row.action && entry.keys === row.chord && sameParams(entry.params, row.params);
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

function isOverridable(action: EditorAction): boolean {
    return action.customizable && isNodeAction(action) && action.defaultChords.length > 0;
}

function requireCustomizable(actionId: EditorActionId): EditorAction {
    const action = ACTIONS_BY_ID.get(actionId);
    if (!action?.customizable) {
        throw new Error(`Shortcut action "${actionId}" cannot have custom keys`);
    }
    return action;
}

function requireOverridable(actionId: EditorActionId): EditorAction {
    const action = ACTIONS_BY_ID.get(actionId);
    if (!action || !isOverridable(action)) {
        throw new Error(`Shortcut action "${actionId}" has no node key to change`);
    }
    return action;
}

function isRecord(value: unknown): value is Readonly<Record<string, unknown>> {
    return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function readCustomEntry(value: unknown): CustomShortcutEntry[] {
    if (!isRecord(value)) {
        return [];
    }
    const action = value['action'];
    const keys = value['keys'];
    if (typeof action !== 'string' || (typeof keys !== 'string' && keys !== null)) {
        return [];
    }
    const params = value['params'];
    return [isShortcutParams(params) ? { action, keys, params } : { action, keys }];
}
