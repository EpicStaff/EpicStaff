import { computed, inject, Injectable, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import {
    ROLE_PERMISSION_EXTENSIONS,
    RolePermissionExtension,
    RolePermissionExtensionError,
    RolePermissionExtensionGrant,
    RolePermissionExtensionRoleState,
    RolePermissionExtensionRow,
} from '@shared/services';
import { catchError, forkJoin, map, Observable, of, Subject, switchMap, tap } from 'rxjs';

import { PermissionMatrixGroup } from './permission-matrix.model';
import { extensionMatrixGroup, permissionKey } from './permission-matrix.util';

/** A failed load or save of one extension's rows, ready to show. */
export interface PermissionExtensionFailure {
    groupLabel: string;
    message: string;
}

/** Ticked cells a load left out because the caller may not grant them in the new rows' organization. */
export interface PermissionExtensionLeftOut {
    groupLabel: string;
    count: number;
}

/** Each cell's required cells, and the cells requiring it (same row; selection keys). */
interface CellDependencies {
    requires: ReadonlyMap<string, readonly string[]>;
    requiredBy: ReadonlyMap<string, readonly string[]>;
}

/** One extension's rows as this dialog holds them. */
interface ExtensionRows {
    readonly extension: RolePermissionExtension;
    readonly rows: readonly RolePermissionExtensionRow[];
    readonly editable: boolean;
    /** The cells the server stores for the role; empty for a role that does not exist yet. */
    readonly storedKeys: ReadonlySet<string>;
}

type ExtensionRowsRequest = { kind: 'organization'; orgId: number } | { kind: 'role'; roleId: number; orgId?: number };

interface ExtensionRowsLoad {
    request: ExtensionRowsRequest;
    entries: ExtensionRows[];
    failures: PermissionExtensionFailure[];
}

/**
 * The rows Roles-matrix extensions add to one role dialog: loads them, keeps what is ticked in them apart from the
 * catalog permissions, and saves them through their extension after the role itself is saved. Provide it on the dialog.
 *
 * Only active extensions are asked. A failed load leaves that extension out, so a save can never overwrite rows that
 * were not shown. A cell the caller may not change (outside what they may grant, or a read-only row) keeps its state
 * through every operation. An action's `requires` is a hard rule: ticking it ticks them, clearing one clears what
 * requires it.
 */
@Injectable()
export class PermissionExtensionRowsService {
    private readonly entries = signal<readonly ExtensionRows[]>([]);
    private readonly selectedSignal = signal<ReadonlySet<string>>(new Set());
    /** The ticked extension cells. */
    readonly selected = this.selectedSignal.asReadonly();
    private readonly isLoadingSignal = signal(false);
    readonly isLoading = this.isLoadingSignal.asReadonly();
    private readonly loadFailuresSignal = signal<PermissionExtensionFailure[]>([]);
    /** Extensions whose rows could not be loaded by the last load. */
    readonly loadFailures = this.loadFailuresSignal.asReadonly();
    private readonly leftOutSignal = signal<PermissionExtensionLeftOut[]>([]);
    /** What the last load for an organization dropped from the selection, per extension. */
    readonly leftOut = this.leftOutSignal.asReadonly();

    /** One group per extension that has rows, in provider order. */
    readonly groups = computed<PermissionMatrixGroup[]>(() =>
        this.entries()
            .filter((entry) => entry.rows.length > 0)
            .map((entry) => extensionMatrixGroup(entry.extension, entry.rows))
    );

    /**
     * Cells that cannot be ticked or cleared now: locked ones (outside the caller's grantable actions, or in read-only
     * rows); an unticked one requiring a locked, unticked cell; a ticked one that a locked, ticked cell requires.
     */
    readonly disabledKeys = computed<ReadonlySet<string>>(() => {
        const locked = this.lockedKeys();
        const selected = this.selectedSignal();
        const { requires, requiredBy } = this.dependencies();
        const disabled = new Set(locked);
        for (const key of this.ownedKeys()) {
            if (locked.has(key)) continue;
            const blockedTick =
                !selected.has(key) && (requires.get(key) ?? []).some((cell) => locked.has(cell) && !selected.has(cell));
            const blockedClear =
                selected.has(key) && (requiredBy.get(key) ?? []).some((cell) => locked.has(cell) && selected.has(cell));
            if (blockedTick || blockedClear) disabled.add(key);
        }
        return disabled;
    });

    /** Whether a save would change what the server stores. */
    readonly hasChanges = computed(() => this.changedEntries().length > 0);

    private readonly ownedKeys = computed<ReadonlySet<string>>(
        () => new Set(this.entries().flatMap((entry) => entryKeys(entry)))
    );
    /** Cells the caller may never change here: outside what they may grant, or in read-only rows. */
    private readonly lockedKeys = computed<ReadonlySet<string>>(() => {
        const locked = new Set<string>();
        for (const entry of this.entries()) {
            for (const row of entry.rows) {
                for (const cell of row.actions) {
                    if (!entry.editable || !row.grantable.includes(cell.action)) {
                        locked.add(permissionKey(row.code, cell.action));
                    }
                }
            }
        }
        return locked;
    });
    private readonly dependencies = computed<CellDependencies>(() => {
        const requires = new Map<string, string[]>();
        const requiredBy = new Map<string, string[]>();
        for (const entry of this.entries()) {
            for (const row of entry.rows) {
                const actions = new Set(row.actions.map((cell) => cell.action));
                for (const cell of row.actions) {
                    const key = permissionKey(row.code, cell.action);
                    const required = cell.requires
                        .filter((action) => action !== cell.action && actions.has(action))
                        .map((action) => permissionKey(row.code, action));
                    requires.set(key, required);
                    for (const requiredKey of required) {
                        requiredBy.set(requiredKey, [...(requiredBy.get(requiredKey) ?? []), key]);
                    }
                }
            }
        }
        return { requires, requiredBy };
    });
    private readonly changedEntries = computed<ExtensionRows[]>(() => {
        const selected = this.selectedSignal();
        return this.entries().filter((entry) => {
            const current = entryKeys(entry).filter((key) => selected.has(key));
            return current.length !== entry.storedKeys.size || current.some((key) => !entry.storedKeys.has(key));
        });
    });

    private readonly extensions = inject(ROLE_PERMISSION_EXTENSIONS, { optional: true }) ?? [];
    private readonly requests = new Subject<ExtensionRowsRequest | null>();

    constructor() {
        this.requests
            .pipe(
                switchMap((request) => (request ? this.load(request) : of(null))),
                takeUntilDestroyed()
            )
            .subscribe((loaded) => {
                this.isLoadingSignal.set(false);
                if (loaded) this.apply(loaded);
            });
    }

    /** Whether the cell belongs to an extension row (and not to the catalog). */
    owns(key: string): boolean {
        return this.ownedKeys().has(key);
    }

    /**
     * Loads the rows for a role about to be created in `orgId`; `null` shows none. When the rows land, the selection
     * keeps only cells of those rows the caller may grant, so a seeded or earlier selection carries over where it fits.
     */
    loadForOrg(orgId: number | null): void {
        this.entries.set([]);
        this.loadFailuresSignal.set([]);
        this.leftOutSignal.set([]);
        this.isLoadingSignal.set(orgId !== null);
        this.requests.next(orgId === null ? null : { kind: 'organization', orgId });
    }

    /** Loads an existing role's rows; the selection becomes what the role holds. */
    loadForRole(roleId: number, orgId?: number): void {
        this.entries.set([]);
        this.loadFailuresSignal.set([]);
        this.leftOutSignal.set([]);
        this.isLoadingSignal.set(true);
        this.requests.next({ kind: 'role', roleId, orgId });
    }

    /** Sets the selection before the rows are loaded, e.g. from the role a duplicate is made of. */
    seedSelection(keys: Iterable<string>): void {
        this.selectedSignal.set(new Set(keys));
    }

    /**
     * Ticks or clears the given cells. Ticking also ticks what a cell requires; clearing also clears what requires it,
     * and is refused when a locked, ticked cell requires it. Cells of no extension row and disabled cells are ignored.
     */
    setSelected(keys: Iterable<string>, select: boolean): void {
        const owned = this.ownedKeys();
        const disabled = this.disabledKeys();
        const locked = this.lockedKeys();
        const { requires, requiredBy } = this.dependencies();
        const next = new Set(this.selectedSignal());
        for (const key of keys) {
            if (!owned.has(key) || disabled.has(key)) continue;
            if (select) {
                const required = reachable(key, requires);
                if (required.some((cell) => locked.has(cell) && !next.has(cell))) continue;
                next.add(key);
                for (const cell of required) next.add(cell);
            } else {
                const dependents = reachable(key, requiredBy);
                if (dependents.some((cell) => locked.has(cell) && next.has(cell))) continue;
                next.delete(key);
                for (const cell of dependents) next.delete(cell);
            }
        }
        this.selectedSignal.set(next);
    }

    /**
     * Makes `keys` the selection of every cell that can be changed (Select All, Clear All); disabled cells keep their
     * state, and a ticked cell whose requirement ends up cleared is cleared too.
     */
    replaceSelection(keys: Iterable<string>): void {
        const wanted = new Set(keys);
        const disabled = this.disabledKeys();
        const next = new Set(this.selectedSignal());
        for (const key of this.ownedKeys()) {
            if (disabled.has(key)) continue;
            if (wanted.has(key)) next.add(key);
            else next.delete(key);
        }
        this.selectedSignal.set(this.withRequirements(next));
    }

    /**
     * Saves every extension whose rows changed, each with all of its rows (the extensions replace what the role holds).
     * Emits the failures, empty when everything was saved or nothing changed; never errors. A saved extension's rows
     * and selection become what the server answered.
     */
    save(roleId: number): Observable<PermissionExtensionFailure[]> {
        const changed = this.changedEntries();
        if (changed.length === 0) return of([]);
        const selected = this.selectedSignal();
        return forkJoin(
            changed.map((entry) =>
                entry.extension.saveRole(roleId, grantsOf(entry, selected)).pipe(
                    tap((state) => this.replaceEntry(toEntry(entry.extension, state))),
                    map((): PermissionExtensionFailure | null => null),
                    catchError((error: unknown) =>
                        of(
                            failureOf(
                                entry.extension,
                                error,
                                `Couldn't save the ${entry.extension.groupLabel} permissions.`
                            )
                        )
                    )
                )
            )
        ).pipe(map((results) => results.filter((result): result is PermissionExtensionFailure => result !== null)));
    }

    private load(request: ExtensionRowsRequest): Observable<ExtensionRowsLoad> {
        const active = this.extensions.filter((extension) => extension.isActive());
        if (active.length === 0) return of({ request, entries: [], failures: [] });
        return forkJoin(
            active.map((extension) =>
                this.loadEntry(extension, request).pipe(
                    map((entry) => ({ entry, failure: null })),
                    catchError((error: unknown) =>
                        of({
                            entry: null,
                            failure: failureOf(
                                extension,
                                error,
                                `Couldn't load the ${extension.groupLabel} permissions.`
                            ),
                        })
                    )
                )
            )
        ).pipe(
            map((results) => ({
                request,
                entries: results.flatMap((result) => (result.entry ? [result.entry] : [])),
                failures: results.flatMap((result) => (result.failure ? [result.failure] : [])),
            }))
        );
    }

    private loadEntry(extension: RolePermissionExtension, request: ExtensionRowsRequest): Observable<ExtensionRows> {
        if (request.kind === 'organization') {
            return extension
                .rowsForOrg(request.orgId)
                .pipe(map((rows) => ({ extension, rows, editable: true, storedKeys: new Set<string>() })));
        }
        return extension.roleState(request.roleId, request.orgId).pipe(map((state) => toEntry(extension, state)));
    }

    private apply(loaded: ExtensionRowsLoad): void {
        this.entries.set(loaded.entries);
        this.loadFailuresSignal.set(loaded.failures);
        if (loaded.request.kind === 'role') {
            this.selectedSignal.set(new Set(loaded.entries.flatMap((entry) => [...entry.storedKeys])));
            return;
        }
        // A carried-over selection keeps only what the caller may grant in the new rows, and what that still needs.
        const owned = this.ownedKeys();
        const locked = this.lockedKeys();
        const before = this.selectedSignal();
        const kept = this.withRequirements(new Set([...before].filter((key) => owned.has(key) && !locked.has(key))));
        const dropped = new Set([...before].filter((key) => owned.has(key) && !kept.has(key)));
        this.selectedSignal.set(kept);
        this.leftOutSignal.set(
            loaded.entries.flatMap((entry) => {
                const count = entryKeys(entry).filter((key) => dropped.has(key)).length;
                return count > 0 ? [{ groupLabel: entry.extension.groupLabel, count }] : [];
            })
        );
    }

    /** `selection` without the unlocked cells whose requirements are not all ticked (repeated until none is left). */
    private withRequirements(selection: Set<string>): Set<string> {
        const locked = this.lockedKeys();
        const { requires } = this.dependencies();
        let removed = true;
        while (removed) {
            removed = false;
            for (const key of selection) {
                if (locked.has(key)) continue;
                if ((requires.get(key) ?? []).some((cell) => !selection.has(cell))) {
                    selection.delete(key);
                    removed = true;
                }
            }
        }
        return selection;
    }

    private replaceEntry(saved: ExtensionRows): void {
        const previous = this.entries().find((entry) => entry.extension === saved.extension);
        this.entries.update((entries) => entries.map((entry) => (entry.extension === saved.extension ? saved : entry)));
        const next = new Set(this.selectedSignal());
        if (previous) for (const key of entryKeys(previous)) next.delete(key);
        for (const key of saved.storedKeys) next.add(key);
        this.selectedSignal.set(next);
    }
}

/** Every cell reachable from `key` through `links` (its requirements, or what requires it), without `key`. */
function reachable(key: string, links: ReadonlyMap<string, readonly string[]>): string[] {
    const found = new Set<string>();
    const pending = [...(links.get(key) ?? [])];
    while (pending.length > 0) {
        const cell = pending.pop()!;
        if (cell === key || found.has(cell)) continue;
        found.add(cell);
        pending.push(...(links.get(cell) ?? []));
    }
    return [...found];
}

function entryKeys(entry: ExtensionRows): string[] {
    return entry.rows.flatMap((row) => row.actions.map((cell) => permissionKey(row.code, cell.action)));
}

function grantsOf(entry: ExtensionRows, selected: ReadonlySet<string>): RolePermissionExtensionGrant[] {
    return entry.rows.map((row) => ({
        code: row.code,
        actions: row.actions
            .map((cell) => cell.action)
            .filter((action) => selected.has(permissionKey(row.code, action))),
    }));
}

function toEntry(extension: RolePermissionExtension, state: RolePermissionExtensionRoleState): ExtensionRows {
    return {
        extension,
        rows: state.rows,
        editable: state.editable,
        storedKeys: new Set(
            state.granted.flatMap((grant) => grant.actions.map((action) => permissionKey(grant.code, action)))
        ),
    };
}

function failureOf(extension: RolePermissionExtension, error: unknown, fallback: string): PermissionExtensionFailure {
    return {
        groupLabel: extension.groupLabel,
        message: error instanceof RolePermissionExtensionError ? error.message : fallback,
    };
}
