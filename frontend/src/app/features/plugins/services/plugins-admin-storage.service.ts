import { inject, Injectable, signal } from '@angular/core';
import { StorageService } from '@shared/services';
import { finalize, Observable, tap } from 'rxjs';

import { ApiGetRequest } from '../../../core/models/api-request.model';
import {
    PackageReview,
    PluginDetail,
    PluginGrant,
    PluginSummary,
    PluginUploadEvent,
} from '../models/plugin-admin.model';
import { PluginsAdminApiService } from './plugins-admin-api.service';

/**
 * The SuperAdmin plugin list, kept in step with what is done to it here (upload, approve, reject, grant). Registered
 * in `APP_STORAGE`, so logout clears it; a response that lands after `clear()` is dropped.
 */
@Injectable({ providedIn: 'root' })
export class PluginsAdminStorageService implements StorageService {
    private readonly pluginsSignal = signal<PluginSummary[]>([]);
    /** Sorted by name, like the backend. */
    public readonly plugins = this.pluginsSignal.asReadonly();

    private readonly isLoadingSignal = signal(false);
    public readonly isLoading = this.isLoadingSignal.asReadonly();

    private readonly isLoadedSignal = signal(false);
    public readonly isLoaded = this.isLoadedSignal.asReadonly();

    private readonly api = inject(PluginsAdminApiService);
    /** Bumped by `clear()`; a response from an older generation is dropped. */
    private generation = 0;

    loadPlugins(): Observable<PluginSummary[]> {
        const generation = this.generation;
        this.isLoadingSignal.set(true);
        return this.api.listPlugins().pipe(
            tap((plugins) => {
                if (generation !== this.generation) return;
                this.pluginsSignal.set(plugins);
                this.isLoadedSignal.set(true);
            }),
            finalize(() => {
                if (generation === this.generation) this.isLoadingSignal.set(false);
            })
        );
    }

    getPlugin(identifier: string): Observable<PluginDetail> {
        return this.whenCurrent(this.api.getPlugin(identifier), (plugin) => this.upsert(plugin));
    }

    /** The upload creates or replaces a pending package, so the list is reloaded once it is stored. */
    uploadPackage(file: File): Observable<PluginUploadEvent> {
        return this.api.uploadPackage(file).pipe(
            tap((event) => {
                if (event.kind === 'done') this.loadPlugins().subscribe({ error: () => undefined });
            })
        );
    }

    getPackageReview(packageId: number): Observable<PackageReview> {
        return this.api.getPackageReview(packageId);
    }

    approvePackage(packageId: number, untrustedAcknowledged: boolean): Observable<PluginDetail> {
        return this.whenCurrent(this.api.approvePackage(packageId, untrustedAcknowledged), (plugin) =>
            this.upsert(plugin)
        );
    }

    /** Rejecting deletes the package, and the plugin too when it had nothing approved; the list is reloaded. */
    rejectPackage(packageId: number): Observable<void> {
        return this.api
            .rejectPackage(packageId)
            .pipe(tap(() => this.loadPlugins().subscribe({ error: () => undefined })));
    }

    listGrants(identifier: string, page: number, pageSize: number): Observable<ApiGetRequest<PluginGrant>> {
        return this.api.listGrants(identifier, page, pageSize);
    }

    createGrant(identifier: string, organizationId: number): Observable<PluginGrant> {
        return this.whenCurrent(this.api.createGrant(identifier, organizationId), (grant) => {
            if (grant.state !== 'active') return;
            this.pluginsSignal.update((plugins) =>
                plugins.map((plugin) =>
                    plugin.identifier === identifier ? { ...plugin, grant_count: plugin.grant_count + 1 } : plugin
                )
            );
        });
    }

    clear(): void {
        this.generation++;
        this.pluginsSignal.set([]);
        this.isLoadingSignal.set(false);
        this.isLoadedSignal.set(false);
    }

    /** Runs `apply` with the result unless the storage was cleared while the request was under way. */
    private whenCurrent<Result>(request: Observable<Result>, apply: (result: Result) => void): Observable<Result> {
        const generation = this.generation;
        return request.pipe(
            tap((result) => {
                if (generation === this.generation) apply(result);
            })
        );
    }

    /** Puts a plugin's summary into the list (a detail carries more than the list needs). */
    private upsert(plugin: PluginDetail): void {
        const summary = toSummary(plugin);
        this.pluginsSignal.update((plugins) => {
            const index = plugins.findIndex((existing) => existing.identifier === summary.identifier);
            if (index === -1) return [...plugins, summary].sort(byName);
            const next = [...plugins];
            next[index] = summary;
            return next;
        });
    }
}

function toSummary(plugin: PluginDetail): PluginSummary {
    return {
        identifier: plugin.identifier,
        name: plugin.name,
        description: plugin.description,
        state: plugin.state,
        trust: plugin.trust,
        current_version: plugin.current_version,
        icon_url: plugin.icon_url,
        frame_origin: plugin.frame_origin,
        grant_count: plugin.grant_count,
        pending_package: plugin.pending_package,
        created_at: plugin.created_at,
    };
}

function byName(first: PluginSummary, second: PluginSummary): number {
    return first.name.localeCompare(second.name) || first.identifier.localeCompare(second.identifier);
}
