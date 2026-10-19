import { computed, DestroyRef, inject, Injectable, InjectionToken, linkedSignal, NgZone, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { CustomShortcutEntry, ShortcutSettings } from '@shared/models';
import { catchError, concatMap, EMPTY, finalize, fromEvent, Subject } from 'rxjs';

import { ProfileService } from '../../services/auth/profile.service';
import { ToastService } from '../../services/notifications';
import { EDITOR_ACTIONS, EditorActionId } from '../core/keymap/editor-actions';
import { chordFromEvent, isEditableTarget, isInsideSidePanel, KeyChord } from '../core/keymap/key-chord.util';
import {
    applyShortcutChange,
    CustomShortcutRow,
    haveSameEntries,
    identifyRows,
    readCustomEntries,
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
}

export type CustomShortcutCheck = ShortcutRejected | (ShortcutAccepted & { readonly customShortcutId: string });

const NODE_ACTION_IDS: ReadonlySet<EditorActionId> = new Set(
    EDITOR_ACTIONS.filter((action) => action.section === 'Nodes').map((action) => action.id)
);

type KeyHandler = (event: KeyboardEvent) => void;

interface Registration {
    readonly handler: KeyHandler;
    readonly allowInEditable: boolean;
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

    private readonly rows = linkedSignal<
        { saved: readonly CustomShortcutEntry[]; pending: number },
        readonly CustomShortcutRow[]
    >({
        source: () => ({
            saved: readCustomEntries(this.profileService.shortcutSettings()),
            pending: this.pendingSaves(),
        }),
        computation: (source, previous) => {
            if (previous && (source.pending > 0 || haveSameEntries(source.saved, previous.value))) {
                return previous.value;
            }
            return identifyRows(source.saved, previous?.value ?? [], () => this.createRowId());
        },
    });

    private readonly resolved = computed(() => resolveShortcuts(this.rows()));

    readonly bindings = computed(() => this.resolved().bindings);

    readonly builtInBindings = computed(() => this.resolved().builtInBindings);

    readonly customShortcuts = computed(() => this.resolved().customShortcuts);

    readonly unboundIds = computed(() => this.resolved().unboundIds);

    readonly defaultsResetClearCount = computed(() => this.resolved().defaultsResetClearCount);

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
        options?: { allowInEditable?: boolean; destroyRef?: DestroyRef }
    ): () => void {
        const registration: Registration = { handler, allowInEditable: options?.allowInEditable ?? false };
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
        const change: ShortcutChange =
            target.customShortcutId === undefined
                ? { kind: 'add-custom', id: '', action: target.action, chord }
                : { kind: 'update-custom', id: target.customShortcutId, action: target.action, chord };
        return toCheck(applyShortcutChange(this.rows(), change));
    }

    addCustom(actionId: EditorActionId, chord: KeyChord | null): CustomShortcutCheck {
        const id = this.createRowId();
        const result = this.apply({ kind: 'add-custom', id, action: actionId, chord });
        return result.accepted ? { accepted: true, displaces: result.displaces, customShortcutId: id } : result;
    }

    updateCustom(
        customShortcutId: string,
        changes: { readonly action?: EditorActionId; readonly chord?: KeyChord | null }
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
            })
        );
    }

    removeCustom(customShortcutId: string): void {
        this.apply({ kind: 'remove-custom', id: customShortcutId });
    }

    resetToDefaults(): void {
        this.apply({ kind: 'reset-to-defaults' });
    }

    private apply(change: ShortcutChange): ShortcutChangeResult {
        const result = applyShortcutChange(this.rows(), change);
        if (result.accepted && !haveSameEntries(toShortcutSettings(result.rows).custom, this.customShortcuts())) {
            this.save(result.rows);
        }
        return result;
    }

    private save(next: readonly CustomShortcutRow[]): void {
        this.pendingSaves.update((count) => count + 1);
        this.rows.set(next);
        this.saveQueue.next(toShortcutSettings(next));
    }

    private createRowId(): string {
        this.lastRowId += 1;
        return `custom-${this.lastRowId}`;
    }

    private dispatch(event: KeyboardEvent): void {
        const chord = chordFromEvent(event, this.isMac);
        const actionId = chord === null ? undefined : this.resolved().holders.get(chord)?.action;
        const registrations = actionId === undefined ? [] : (this.registrations.get(actionId) ?? []);
        if (!actionId || registrations.length === 0 || this.isSuppressed(actionId, event)) {
            return;
        }

        const target = event.target;
        const fromEditable = target instanceof HTMLElement && isEditableTarget(target);
        const runnable = registrations.filter((registration) => !fromEditable || registration.allowInEditable);
        if (runnable.length === 0) {
            return;
        }

        event.preventDefault();
        event.stopPropagation();
        this.ngZone.run(() => runnable.forEach((registration) => registration.handler(event)));
    }

    private isSuppressed(actionId: EditorActionId, event: KeyboardEvent): boolean {
        if (NODE_ACTION_IDS.has(actionId)) {
            return event.repeat || (event.target instanceof Element && isInsideSidePanel(event.target));
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
