import { computed, DestroyRef, inject, Injectable, InjectionToken, linkedSignal, NgZone, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { catchError, concatMap, EMPTY, finalize, fromEvent, Subject } from 'rxjs';

import { ProfileService } from '../../services/auth/profile.service';
import { ToastService } from '../../services/notifications';
import { EDITOR_ACTIONS, EditorAction, EditorActionId } from '../core/keymap/editor-actions';
import {
    checkUserChord,
    chordFromEvent,
    ChordRejection,
    isEditableTarget,
    isInsideSidePanel,
    KeyChord,
} from '../core/keymap/key-chord.util';

export const PLATFORM_IS_MAC = new InjectionToken<boolean>('PLATFORM_IS_MAC', {
    providedIn: 'root',
    factory: () => /Mac|iPhone|iPad/.test(navigator.platform || navigator.userAgent),
});

const NODE_ACTION_IDS: ReadonlySet<EditorActionId> = new Set(
    EDITOR_ACTIONS.filter((action) => action.section === 'Nodes').map((action) => action.id)
);

type ShortcutOverrides = Readonly<Record<string, string>>;

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

    private readonly overrides = linkedSignal<{ saved: ShortcutOverrides; pending: number }, ShortcutOverrides>({
        source: () => ({ saved: this.profileService.shortcutOverrides(), pending: this.pendingSaves() }),
        computation: (source, previous) => {
            if (!previous) return source.saved;
            if (source.pending > 0 || haveSameEntries(source.saved, previous.value)) return previous.value;
            return source.saved;
        },
    });

    private readonly resolved = computed(() => resolveBindings(this.overrides()));

    readonly bindings = computed(() => this.resolved().bindings);

    readonly overriddenIds = computed(() => this.resolved().overriddenIds);

    private readonly actionByChord = computed(() => {
        const actionByChord = new Map<KeyChord, EditorActionId>();
        this.bindings().forEach((chords, actionId) => chords.forEach((chord) => actionByChord.set(chord, actionId)));
        return actionByChord;
    });

    private readonly registrations = new Map<EditorActionId, Registration[]>();
    private readonly saveQueue = new Subject<ShortcutOverrides>();

    constructor() {
        this.ngZone.runOutsideAngular(() =>
            fromEvent<KeyboardEvent>(window, 'keydown')
                .pipe(takeUntilDestroyed(this.destroyRef))
                .subscribe((event) => this.dispatch(event))
        );

        this.saveQueue
            .pipe(
                concatMap((overrides) =>
                    this.profileService.updateShortcutOverrides(overrides).pipe(
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
        return this.actionByChord().get(chord) ?? null;
    }

    setOverride(actionId: EditorActionId, chord: KeyChord): ChordRejection | null {
        const action = findRebindableAction(actionId);
        const owner = this.actionByChord().get(chord);
        const rejection = checkUserChord(chord, owner !== undefined && owner !== actionId ? owner : null);
        if (rejection) {
            return rejection;
        }

        const current = this.overrides();
        const others = Object.fromEntries(Object.entries(current).filter(([key]) => key !== actionId));
        const isDefault = action.defaultChords.length === 1 && action.defaultChords[0] === chord;
        const next: ShortcutOverrides = isDefault ? others : { ...others, [actionId]: chord };
        if (!haveSameEntries(next, current)) {
            this.save(next);
        }
        return null;
    }

    resetOverride(actionId: EditorActionId): ChordRejection | null {
        const [defaultChord] = findRebindableAction(actionId).defaultChords;
        return this.setOverride(actionId, defaultChord);
    }

    private save(next: ShortcutOverrides): void {
        this.pendingSaves.update((count) => count + 1);
        this.overrides.set(next);
        this.saveQueue.next(next);
    }

    private dispatch(event: KeyboardEvent): void {
        const chord = chordFromEvent(event, this.isMac);
        const actionId = chord === null ? undefined : this.actionByChord().get(chord);
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

function findRebindableAction(actionId: EditorActionId): EditorAction {
    const action = EDITOR_ACTIONS.find((candidate) => candidate.id === actionId);
    if (!action?.rebindable) {
        throw new Error(`Shortcut action "${actionId}" cannot be rebound`);
    }
    return action;
}

interface ResolvedBindings {
    readonly bindings: ReadonlyMap<EditorActionId, readonly KeyChord[]>;
    readonly overriddenIds: ReadonlySet<EditorActionId>;
}

function resolveBindings(overrides: ShortcutOverrides): ResolvedBindings {
    const requested = new Map<EditorActionId, KeyChord>();
    for (const action of EDITOR_ACTIONS) {
        const chord: unknown = Object.hasOwn(overrides, action.id) ? overrides[action.id] : undefined;
        if (action.rebindable && typeof chord === 'string' && checkUserChord(chord, null) === null) {
            requested.set(action.id, chord);
        }
    }

    const owners = new Map<KeyChord, EditorActionId>();
    for (const action of EDITOR_ACTIONS) {
        if (!requested.has(action.id)) {
            action.defaultChords.forEach((chord) => owners.set(chord, action.id));
        }
    }

    const granted = new Map<EditorActionId, KeyChord>();
    requested.forEach((chord, actionId) => {
        if (!owners.has(chord)) {
            owners.set(chord, actionId);
            granted.set(actionId, chord);
        }
    });

    const bindings = new Map<EditorActionId, readonly KeyChord[]>();
    for (const action of EDITOR_ACTIONS) {
        const grantedChord = granted.get(action.id);
        if (grantedChord !== undefined) {
            bindings.set(action.id, [grantedChord]);
            continue;
        }
        const chords = action.defaultChords.filter((chord) => (owners.get(chord) ?? action.id) === action.id);
        chords.forEach((chord) => owners.set(chord, action.id));
        bindings.set(action.id, chords);
    }
    return { bindings, overriddenIds: new Set(granted.keys()) };
}

function haveSameEntries(first: ShortcutOverrides, second: ShortcutOverrides): boolean {
    const firstKeys = Object.keys(first);
    return (
        firstKeys.length === Object.keys(second).length &&
        firstKeys.every((key) => Object.hasOwn(second, key) && first[key] === second[key])
    );
}
