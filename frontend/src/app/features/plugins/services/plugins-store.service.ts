import { HttpErrorResponse } from '@angular/common/http';
import { effect, inject, Injectable, signal, untracked } from '@angular/core';
import { ActionCode, ResourceCode } from '@shared/models';
import { StorageService } from '@shared/services';
import { catchError, EMPTY, exhaustMap, finalize, forkJoin, interval, Observable, of, Subscription, tap } from 'rxjs';

import { ActiveOrgService } from '../../../services/auth/active-org.service';
import { PermissionsService } from '../../../services/auth/permissions.service';
import {
    PluginDetail,
    PluginInstallEvent,
    PluginNavItem,
    PluginSecretsRequest,
    PluginSecretValues,
    PluginSummary,
} from '../models/plugin.model';
import { PluginsApiService } from './plugins-api.service';

/** How often a plugin that is preparing its knowledge is re-read (the API contract's 5 s). */
export const PLUGIN_POLL_INTERVAL_MS = 5000;

/** A plugin gets a navigation button only when its page can actually be opened. */
export function isNavPlugin(plugin: PluginSummary): boolean {
    return plugin.status === 'ready' && !plugin.suspended && plugin.has_ui;
}

/** Sorted ids of the plugins that should have a navigation button; compared to spot a change. */
function navSignature(plugins: readonly PluginSummary[]): string {
    return plugins
        .filter(isNavPlugin)
        .map((plugin) => plugin.id)
        .sort((first, second) => first - second)
        .join(',');
}

/**
 * Installed plugins of the active organization, and its plugin navigation buttons.
 *
 * Registered in `APP_STORAGE` (`providePluginsStorages`), so `clear()` runs on org switch and
 * logout. While any plugin is `preparing`, each such plugin is re-read every
 * {@link PLUGIN_POLL_INTERVAL_MS} until it turns `ready` or `needs_attention`.
 *
 * The buttons come from their own endpoint (`GET /api/plugins/nav/`, `plugins:use`), because a
 * role that may only open plugin pages can't read the list. They reload whenever the active
 * organization or the `plugins:use` permission changes (so they come back after an org switch),
 * and whenever a change made here adds or removes a button (install, suspend, resume, delete,
 * or polling that sees a plugin turn ready).
 */
@Injectable({ providedIn: 'root' })
export class PluginsStoreService implements StorageService {
    private readonly pluginsApiService = inject(PluginsApiService);
    private readonly activeOrgService = inject(ActiveOrgService);
    private readonly permissionsService = inject(PermissionsService);

    private readonly pluginsSignal = signal<PluginSummary[]>([]);
    public readonly plugins = this.pluginsSignal.asReadonly();

    private readonly loadingSignal = signal(false);
    public readonly loading = this.loadingSignal.asReadonly();

    private readonly loadedSignal = signal(false);
    /** True once the list has loaded for the active organization; reset by `clear()`. */
    public readonly loaded = this.loadedSignal.asReadonly();

    private readonly navPluginsSignal = signal<PluginNavItem[]>([]);
    /** Navigation buttons of the active organization; `[]` without `plugins:use`. */
    public readonly navPlugins = this.navPluginsSignal.asReadonly();

    private readonly navSyncEffect = effect(() => {
        const orgId = this.activeOrgService.activeOrgId();
        const canUse = this.permissionsService.can(ResourceCode.Plugins, ActionCode.Use);
        untracked(() => (orgId !== null && canUse ? this.refreshNav() : this.resetNav()));
    });

    private pollSubscription: Subscription | null = null;
    private navSubscription: Subscription | null = null;
    // Bumped by `clear()` (org switch / logout). A response tagged with an older generation
    // belongs to the previous organization and is dropped instead of written into the signals.
    private generation = 0;

    /** Loads the list fresh. Starts or stops polling to match the result. */
    refresh(): Observable<PluginSummary[]> {
        const generation = this.generation;
        this.loadingSignal.set(true);
        return this.pluginsApiService.list().pipe(
            tap((plugins) => {
                if (generation !== this.generation) return;
                this.loadedSignal.set(true);
                this.setPlugins(plugins);
            }),
            finalize(() => {
                if (generation === this.generation) this.loadingSignal.set(false);
            })
        );
    }

    /** Reloads the navigation buttons; a failed reload keeps the current ones. */
    refreshNav(): void {
        const generation = this.generation;
        this.navSubscription?.unsubscribe();
        this.navSubscription = this.pluginsApiService.listNav().subscribe({
            next: (items) => {
                if (generation === this.generation) this.navPluginsSignal.set(items);
            },
            error: () => undefined,
        });
    }

    suspend(id: number): Observable<PluginDetail> {
        return this.applyDetail(this.pluginsApiService.suspend(id));
    }

    resume(id: number): Observable<PluginDetail> {
        return this.applyDetail(this.pluginsApiService.resume(id));
    }

    retry(id: number): Observable<PluginDetail> {
        return this.applyDetail(this.pluginsApiService.retry(id));
    }

    updateSecrets(id: number, request: PluginSecretsRequest): Observable<PluginDetail> {
        return this.applyDetail(this.pluginsApiService.updateSecrets(id, request));
    }

    delete(id: number): Observable<void> {
        const generation = this.generation;
        return this.pluginsApiService.delete(id).pipe(
            tap(() => {
                if (generation === this.generation) this.remove(id);
            })
        );
    }

    /** Emits upload progress, then the installed plugin, which is added to the list. */
    install(file: File, secrets: PluginSecretValues): Observable<PluginInstallEvent> {
        const generation = this.generation;
        return this.pluginsApiService.install(file, secrets).pipe(
            tap((event) => {
                if (event.kind === 'done' && generation === this.generation) this.upsert(event.plugin);
            })
        );
    }

    clear(): void {
        this.generation++;
        this.stopPolling();
        this.resetNav();
        this.pluginsSignal.set([]);
        this.loadingSignal.set(false);
        this.loadedSignal.set(false);
    }

    private applyDetail(request: Observable<PluginDetail>): Observable<PluginDetail> {
        const generation = this.generation;
        return request.pipe(
            tap((plugin) => {
                if (generation === this.generation) this.upsert(plugin);
            })
        );
    }

    private setPlugins(plugins: PluginSummary[]): void {
        const navChanged = navSignature(this.pluginsSignal()) !== navSignature(plugins);
        this.pluginsSignal.set(plugins);
        this.syncPolling();
        if (navChanged) this.refreshNav();
    }

    private resetNav(): void {
        this.navSubscription?.unsubscribe();
        this.navSubscription = null;
        this.navPluginsSignal.set([]);
    }

    private upsert(plugin: PluginSummary): void {
        const plugins = this.pluginsSignal();
        const index = plugins.findIndex((existing) => existing.id === plugin.id);
        if (index === -1) {
            this.setPlugins([...plugins, plugin].sort(byNameThenId));
            return;
        }
        const next = [...plugins];
        next[index] = plugin;
        this.setPlugins(next);
    }

    private remove(id: number): void {
        this.setPlugins(this.pluginsSignal().filter((plugin) => plugin.id !== id));
    }

    private syncPolling(): void {
        const hasPreparing = this.pluginsSignal().some((plugin) => plugin.status === 'preparing');
        if (hasPreparing && !this.pollSubscription) {
            this.startPolling();
        } else if (!hasPreparing) {
            this.stopPolling();
        }
    }

    private startPolling(): void {
        const generation = this.generation;
        // exhaustMap: a slow poll is never overlapped by the next tick.
        this.pollSubscription = interval(PLUGIN_POLL_INTERVAL_MS)
            .pipe(exhaustMap(() => this.pollPreparing(generation)))
            .subscribe();
    }

    private stopPolling(): void {
        this.pollSubscription?.unsubscribe();
        this.pollSubscription = null;
    }

    private pollPreparing(generation: number): Observable<unknown> {
        const preparingIds = this.pluginsSignal()
            .filter((plugin) => plugin.status === 'preparing')
            .map((plugin) => plugin.id);
        if (preparingIds.length === 0) return EMPTY;

        return forkJoin(
            preparingIds.map((id) =>
                this.pluginsApiService.get(id).pipe(
                    tap((plugin) => {
                        if (generation === this.generation) this.upsert(plugin);
                    }),
                    catchError((error: HttpErrorResponse) => {
                        // Deleted elsewhere (404) or no longer readable by this role (403): drop it,
                        // so a lost permission doesn't 403 again every tick. Anything else is
                        // treated as transient and retried on the next tick.
                        const gone = error.status === 404 || error.status === 403;
                        if (generation === this.generation && gone) this.remove(id);
                        return of(null);
                    })
                )
            )
        );
    }
}

function byNameThenId(first: PluginSummary, second: PluginSummary): number {
    return first.name.localeCompare(second.name) || first.id - second.id;
}
