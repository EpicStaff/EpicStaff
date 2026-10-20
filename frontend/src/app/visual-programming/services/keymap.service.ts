import { computed, DestroyRef, inject, Injectable, InjectionToken, linkedSignal, NgZone, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { CustomShortcutEntry, ShortcutParams, ShortcutSettings } from '@shared/models';
import { catchError, concatMap, EMPTY, finalize, fromEvent, Subject } from 'rxjs';

import { ProfileService } from '../../services/auth/profile.service';
import { ToastService } from '../../services/notifications';
import { EDITOR_ACTIONS, EditorAction, EditorActionId } from '../core/keymap/editor-actions';
import { chordFromEvent, isEditableTarget, isInsideSidePanel, KeyChord } from '../core/keymap/key-chord.util';
import {
    applyShortcutChange,
    CustomShortcutRow,
    haveSameEntries,
    haveSameOverrides,
    identifyRows,
    KeyOverrides,
    readCustomEntries,
    readKeyOverrides,
    resolveShortcuts,
    ShortcutAccepted,
    ShortcutChange,
    ShortcutChangeResult,
    ShortcutCheck,
    ShortcutRejected,
    toShortcutSettings,
} from '../core/keymap/shortcut-resolution';

export const PLATFORM_IS_MAC = new InjectionToken<boolean>('PLATFORM_IS_MAC', {
    providedIn: 'root',
    factory: () => /Mac|iPhone|iPad/.test(navigator.platform || navigator.userAgent),
});

export interface ShortcutTarget {
    readonly action: EditorActionId;
    readonly customShortcutId?: string;
    readonly params?: ShortcutParams;
}

export interface ShortcutMatch {
    readonly params: ShortcutParams | null;
}

export type CustomShortcutCheck = ShortcutRejected | (ShortcutAccepted & { readonly customShortcutId: string });

const NODE_ACTION_IDS: ReadonlySet<EditorActionId> = new Set(
    EDITOR_ACTIONS.filter((action) => action.section === 'Nodes').map((action) => action.id)
);

const PAN_ACTION_IDS: ReadonlySet<EditorActionId> = new Set(
    EDITOR_ACTIONS.filter((action: EditorAction) => action.pan !== undefined).map((action) => action.id)
);

interface ShortcutState {
    readonly rows: readonly CustomShortcutRow[];
    readonly overrides: KeyOverrides;
}

type KeyHandler = (event: KeyboardEvent, match: ShortcutMatch) => void;

interface Registration {
    readonly handler: KeyHandler;
    readonly allowInEditable: boolean;
    readonly runOutsideAngular: boolean;
    readonly when: ((event: KeyboardEvent) => boolean) | null;
}

@Injectable({ providedIn: 'root' })
export class KeymapService {
    readonly isMac = inject(PLATFORM_IS_MAC);

    private readonly profileService = inject(ProfileService);
    private readonly toastService = inject(ToastService);
    private readonly ngZone = inject(NgZone);
    private readonly destroyRef = inject(DestroyRef);

    private readonly pendingSaves = signal(0);
    private lastRowId = 0;

    private readonly state = linkedSignal<
        { saved: readonly CustomShortcutEntry[]; savedOverrides: KeyOverrides; pending: number },
        ShortcutState
    >({
        source: () => {
            const settings = this.profileService.shortcutSettings();
            return {
                saved: readCustomEntries(settings),
                savedOverrides: readKeyOverrides(settings),
                pending: this.pendingSaves(),
            };
        },
        computation: (source, previous) => {
            const isSame =
                previous !== undefined &&
                haveSameEntries(source.saved, previous.value.rows) &&
                haveSameOverrides(source.savedOverrides, previous.value.overrides);
            if (previous && (source.pending > 0 || isSame)) {
                return previous.value;
            }
            return {
                rows: identifyRows(source.saved, previous?.value.rows ?? [], () => this.createRowId()),
                overrides: source.savedOverrides,
            };
        },
    });

    private readonly resolved = computed(() => resolveShortcuts(this.state().rows, this.state().overrides));

    readonly bindings = computed(() => this.resolved().bindings);

    readonly builtInBindings = computed(() => this.resolved().builtInBindings);

    readonly customShortcuts = computed(() => this.resolved().customShortcuts);

    readonly unboundIds = computed(() => this.resolved().unboundIds);

    readonly overriddenIds = computed<ReadonlySet<EditorActionId>>(() => new Set(this.resolved().overrides.keys()));

    readonly defaultsResetClearCount = computed(() => this.resolved().defaultsResetClearCount);

    readonly canResetToDefaults = computed(
        () => this.resolved().defaultsResetClearCount > 0 || this.resolved().overrides.size > 0
    );

    private readonly registrations = new Map<EditorActionId, Registration[]>();
    private readonly saveQueue = new Subject<ShortcutSettings>();

    constructor() {
        this.ngZone.runOutsideAngular(() =>
            fromEvent<KeyboardEvent>(window, 'keydown')
                .pipe(takeUntilDestroyed(this.destroyRef))
                .subscribe((event) => this.dispatch(event))
        );

        this.saveQueue
            .pipe(
                concatMap((settings) =>
                    this.profileService.updateShortcutSettings(settings).pipe(
                        catchError(() => {
                            if (this.pendingSaves() === 1) {
                                this.toastService.error('Could not save shortcut');
                            }
                            return EMPTY;
                        }),
                        finalize(() => this.pendingSaves.update((count) => count - 1))
                    )
                ),
                takeUntilDestroyed(this.destroyRef)
            )
            .subscribe();
    }

    register(
        actionId: EditorActionId,
        handler: KeyHandler,
        options?: {
            allowInEditable?: boolean;
            runOutsideAngular?: boolean;
            when?: (event: KeyboardEvent) => boolean;
            destroyRef?: DestroyRef;
        }
    ): () => void {
        const registration: Registration = {
            handler,
            allowInEditable: options?.allowInEditable ?? false,
            runOutsideAngular: options?.runOutsideAngular ?? false,
            when: options?.when ?? null,
        };
        this.registrations.set(actionId, [...(this.registrations.get(actionId) ?? []), registration]);
        const unregister = (): void => {
            const remaining = (this.registrations.get(actionId) ?? []).filter((entry) => entry !== registration);
            this.registrations.set(actionId, remaining);
        };
        options?.destroyRef?.onDestroy(unregister);
        return unregister;
    }

    actionForChord(chord: KeyChord): EditorActionId | null {
        return this.resolved().holders.get(chord)?.action ?? null;
    }

    checkChord(chord: KeyChord, target: ShortcutTarget): ShortcutCheck {
        const { action, params } = target;
        const change: ShortcutChange =
            target.customShortcutId === undefined
                ? { kind: 'add-custom', id: '', action, chord, params }
                : { kind: 'update-custom', id: target.customShortcutId, action, chord, params };
        return toCheck(this.preview(change));
    }

    checkNodeKey(actionId: EditorActionId, chord: KeyChord | null): ShortcutCheck {
        return toCheck(this.preview({ kind: 'set-node-key', action: actionId, chord }));
    }

    setNodeKey(actionId: EditorActionId, chord: KeyChord | null): ShortcutCheck {
        return toCheck(this.apply({ kind: 'set-node-key', action: actionId, chord }));
    }

    resetNodeKey(actionId: EditorActionId): ShortcutCheck {
        return toCheck(this.apply({ kind: 'reset-node-key', action: actionId }));
    }

    addCustom(actionId: EditorActionId, chord: KeyChord | null, params?: ShortcutParams): CustomShortcutCheck {
        const id = this.createRowId();
        const result = this.apply({ kind: 'add-custom', id, action: actionId, chord, params });
        return result.accepted ? { accepted: true, displaces: result.displaces, customShortcutId: id } : result;
    }

    updateCustom(
        customShortcutId: string,
        changes: {
            readonly action?: EditorActionId;
            readonly chord?: KeyChord | null;
            readonly params?: ShortcutParams;
        }
    ): ShortcutCheck {
        const row = this.customShortcuts().find((candidate) => candidate.id === customShortcutId);
        if (!row) {
            return { accepted: false, rejection: 'missing', takenBy: null };
        }
        return toCheck(
            this.apply({
                kind: 'update-custom',
                id: customShortcutId,
                action: changes.action ?? row.action,
                chord: changes.chord === undefined ? row.chord : changes.chord,
                params: changes.params ?? row.params,
            })
        );
    }

    removeCustom(customShortcutId: string): void {
        this.apply({ kind: 'remove-custom', id: customShortcutId });
    }

    resetToDefaults(): void {
        this.apply({ kind: 'reset-to-defaults' });
    }

    private preview(change: ShortcutChange): ShortcutChangeResult {
        return applyShortcutChange(this.state().rows, change, this.state().overrides);
    }

    private apply(change: ShortcutChange): ShortcutChangeResult {
        const result = this.preview(change);
        const unchanged =
            result.accepted &&
            haveSameEntries(toShortcutSettings(result.rows).custom, this.customShortcuts()) &&
            haveSameOverrides(result.overrides, this.resolved().overrides);
        if (result.accepted && !unchanged) {
            this.save({ rows: result.rows, overrides: result.overrides });
        }
        return result;
    }

    private save(next: ShortcutState): void {
        this.pendingSaves.update((count) => count + 1);
        this.state.set(next);
        this.saveQueue.next(toShortcutSettings(next.rows, next.overrides));
    }

    private createRowId(): string {
        this.lastRowId += 1;
        return `custom-${this.lastRowId}`;
    }

    private dispatch(event: KeyboardEvent): void {
        const chord = chordFromEvent(event, this.isMac);
        const holder = chord === null ? undefined : this.resolved().holders.get(chord);
        const actionId = holder?.action;
        const registrations = actionId === undefined ? [] : (this.registrations.get(actionId) ?? []);
        if (!actionId || registrations.length === 0 || this.isSuppressed(actionId, event)) {
            return;
        }

        const target = event.target;
        const fromEditable = target instanceof HTMLElement && isEditableTarget(target);
        const runnable = registrations.filter(
            (registration) => (!fromEditable || registration.allowInEditable) && (registration.when?.(event) ?? true)
        );
        if (runnable.length === 0) {
            return;
        }

        event.preventDefault();
        event.stopPropagation();
        const match: ShortcutMatch = { params: holder?.params ?? null };
        runnable
            .filter((registration) => registration.runOutsideAngular)
            .forEach((registration) => registration.handler(event, match));
        const inAngular = runnable.filter((registration) => !registration.runOutsideAngular);
        if (inAngular.length > 0) {
            this.ngZone.run(() => inAngular.forEach((registration) => registration.handler(event, match)));
        }
    }

    private isSuppressed(actionId: EditorActionId, event: KeyboardEvent): boolean {
        const fromSidePanel = event.target instanceof Element && isInsideSidePanel(event.target);
        if (NODE_ACTION_IDS.has(actionId)) {
            return event.repeat || fromSidePanel;
        }
        if (PAN_ACTION_IDS.has(actionId)) {
            return fromSidePanel;
        }
        if (actionId === 'editing.copy') {
            return !!window.getSelection()?.toString();
        }
        return false;
    }
}

function toCheck(result: ShortcutChangeResult): ShortcutCheck {
    return result.accepted ? { accepted: true, displaces: result.displaces } : result;
}
