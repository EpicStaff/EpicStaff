import { HttpErrorResponse } from '@angular/common/http';
import { computed, effect, inject, Injectable, signal, untracked } from '@angular/core';
import { StorageService } from '@shared/services';
import { catchError, defer, finalize, map, Observable, of, retry, shareReplay, throwError, timer } from 'rxjs';

import { ActiveOrgService } from '../../../services/auth/active-org.service';
import { PermissionsService } from '../../../services/auth/permissions.service';
import { ConfigService } from '../../../services/config';
import { AvailablePlugin } from '../models/available-plugin.model';
import { AvailablePluginsApiService } from './available-plugins-api.service';

/** How long a failed list request waits before its one retry (network failures and server errors only). */
export const AVAILABLE_PLUGINS_RETRY_DELAY_MS = 2000;

/** A list request for one organization, until it settles or a newer one replaces it. */
interface PendingLoad {
    readonly orgId: number;
    readonly response: Observable<AvailablePlugin[]>;
}

/**
 * The plugins the signed-in user may open in the active organization: the left bar and the plugin page guard read
 * them. Empty while the plugin platform is off.
 *
 * Loads as soon as the list can be asked for (see {@link loadableOrgId}) and again whenever the active organization
 * changes; a network failure or server error is retried once. Registered in `APP_STORAGE`, so `clear()` runs on org
 * switch and logout; a response that lands after it (it belongs to the previous organization) is dropped, never shown.
 */
@Injectable({ providedIn: 'root' })
export class AvailablePluginsStorageService implements StorageService {
    private readonly pluginsSignal = signal<AvailablePlugin[]>([]);
    /** Sorted by name. */
    public readonly plugins = this.pluginsSignal.asReadonly();

    /**
     * The organization the list may be asked for: the active one, once the signed-in user's permissions in it are known
     * and the plugin platform is on; else `null`. The active organization alone is not enough: a page reload restores it
     * from localStorage when this storage is created, before the config, the session and the profile have loaded, and
     * it does not change once they have.
     */
    private readonly loadableOrgId = computed(() => {
        const orgId = this.activeOrgService.activeOrgId();
        const canLoad =
            orgId !== null &&
            this.permissionsService.isActivePermissionsLoaded() &&
            this.configService.isPluginsEnabled;
        return canLoad ? orgId : null;
    });

    private readonly loadableOrgEffect = effect(() => {
        const orgId = this.loadableOrgId();
        untracked(() => {
            if (orgId === null) {
                this.reset();
                return;
            }
            this.loadForActiveOrg().subscribe();
        });
    });

    private readonly api = inject(AvailablePluginsApiService);
    private readonly activeOrgService = inject(ActiveOrgService);
    private readonly configService = inject(ConfigService);
    private readonly permissionsService = inject(PermissionsService);
    /** The organization {@link plugins} belongs to; `null` until a list landed. */
    private loadedOrgId: number | null = null;
    private pendingLoad: PendingLoad | null = null;

    /**
     * The list for the active organization: the one held when it belongs to that organization, else a fresh load
     * (shared with a load already under way for it). Never fails: a failed load gives `[]`, and so does a call before
     * {@link loadableOrgId} allows one (the plugin page guard runs after the bootstrap guard, so it never makes one).
     */
    loadForActiveOrg(): Observable<AvailablePlugin[]> {
        const orgId = this.loadableOrgId();
        if (orgId === null) return of([]);
        if (this.loadedOrgId === orgId) return of(this.pluginsSignal());
        if (this.pendingLoad?.orgId === orgId) return this.pendingLoad.response;
        return this.startLoad(orgId);
    }

    /** Loads the active organization's list again, even when one is held; the held list stays until the new one lands. */
    refresh(): Observable<AvailablePlugin[]> {
        const orgId = this.loadableOrgId();
        if (orgId === null) return of([]);
        // A load under way is fresh already; replacing it would hand its waiting callers an empty list.
        if (this.pendingLoad?.orgId === orgId) return this.pendingLoad.response;
        return this.startLoad(orgId);
    }

    clear(): void {
        this.reset();
    }

    private startLoad(orgId: number): Observable<AvailablePlugin[]> {
        let load: PendingLoad | null = null;
        const isCurrent = (): boolean => load !== null && this.pendingLoad === load;
        const response = defer(() => this.api.list()).pipe(
            retry({
                count: 1,
                delay: (error: unknown) =>
                    isTransientFailure(error) ? timer(AVAILABLE_PLUGINS_RETRY_DELAY_MS) : throwError(() => error),
            }),
            map((plugins) => {
                // Superseded (org switch, logout, a load for another org): nobody may see it, not even this caller.
                if (!isCurrent() || this.activeOrgService.activeOrgId() !== orgId) return [];
                const sorted = [...plugins].sort(byName);
                this.pluginsSignal.set(sorted);
                this.loadedOrgId = orgId;
                return sorted;
            }),
            catchError(() => of<AvailablePlugin[]>([])),
            finalize(() => {
                if (isCurrent()) this.pendingLoad = null;
            }),
            shareReplay({ bufferSize: 1, refCount: false })
        );
        load = { orgId, response };
        this.pendingLoad = load;
        return response;
    }

    private reset(): void {
        this.pendingLoad = null;
        this.loadedOrgId = null;
        this.pluginsSignal.set([]);
    }
}

/** A failure worth one more try: the network, or the server, not a refusal. */
function isTransientFailure(error: unknown): boolean {
    return error instanceof HttpErrorResponse && (error.status === 0 || error.status >= 500);
}

function byName(first: AvailablePlugin, second: AvailablePlugin): number {
    return first.name.localeCompare(second.name) || first.identifier.localeCompare(second.identifier);
}
