import { inject, Injectable, signal } from '@angular/core';
import { StorageService } from '@shared/services';
import { finalize, Observable, tap } from 'rxjs';

import { ApiGetRequest } from '../../../core/models/api-request.model';
import {
    PackageReview,
    PluginDetail,
    PluginGrant,
    PluginOrgRemovedJob,
    PluginOrgRemovedJobQuery,
    PluginSummary,
    PluginUploadEvent,
} from '../models/plugin-admin.model';
import {
    PluginLimitsResponse,
    PluginLimitsUpdate,
    PluginRuntimeResponse,
    PluginSettingsResponse,
    PluginSettingsUpdate,
} from '../models/plugin-backend.model';
import { PluginGrantPurgePreview, PluginPurgePreview } from '../models/plugin-purge-preview.model';
import { PluginSuspendPreview } from '../models/plugin-suspend-preview.model';
import { PluginsAdminApiService } from './plugins-admin-api.service';

/**
 * The SuperAdmin plugin list, kept in step with what is done to it here (upload, approve, reject, grant, uninstall,
 * reinstall, delete). Registered in `APP_STORAGE`, so logout clears it; a response that lands after `clear()` is
 * dropped.
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

    /** Uninstalling suspends every grant, so the plugin's count of active grants changes with it. */
    uninstallPlugin(identifier: string): Observable<PluginDetail> {
        return this.whenCurrent(this.api.uninstallPlugin(identifier), (plugin) => this.upsert(plugin));
    }

    reinstallPlugin(identifier: string): Observable<PluginDetail> {
        return this.whenCurrent(this.api.reinstallPlugin(identifier), (plugin) => this.upsert(plugin));
    }

    getPluginPurgePreview(identifier: string): Observable<PluginPurgePreview> {
        return this.api.getPluginPurgePreview(identifier);
    }

    purgePlugin(identifier: string, verificationPhrase: string): Observable<PluginDetail> {
        return this.whenCurrent(this.api.purgePlugin(identifier, verificationPhrase), (plugin) => this.upsert(plugin));
    }

    retryRemoval(identifier: string): Observable<PluginDetail> {
        return this.whenCurrent(this.api.retryRemoval(identifier), (plugin) => this.upsert(plugin));
    }

    /** Drops a plugin the server no longer knows, such as one whose deletion has finished. */
    forgetPlugin(identifier: string): void {
        this.pluginsSignal.update((plugins) => plugins.filter((plugin) => plugin.identifier !== identifier));
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

    /** The grant stays out of the active count until the hook succeeds, so the list does not change. */
    retryInstallHook(identifier: string, grantId: number): Observable<PluginGrant> {
        return this.api.retryInstallHook(identifier, grantId);
    }

    getSuspendPreview(identifier: string, grantId: number): Observable<PluginSuspendPreview> {
        return this.api.getSuspendPreview(identifier, grantId);
    }

    /**
     * Suspending and resuming may change the plugin's count of active grants; only the server knows by how much (the
     * grant may have been installing), so reload the plugin with `getPlugin` afterwards.
     */
    suspendGrant(identifier: string, grantId: number): Observable<PluginGrant> {
        return this.api.suspendGrant(identifier, grantId);
    }

    /** As `suspendGrant`: reload the plugin with `getPlugin` afterwards. */
    resumeGrant(identifier: string, grantId: number): Observable<PluginGrant> {
        return this.api.resumeGrant(identifier, grantId);
    }

    getGrantPurgePreview(identifier: string, grantId: number): Observable<PluginGrantPurgePreview> {
        return this.api.getGrantPurgePreview(identifier, grantId);
    }

    /** As `suspendGrant`: reload the plugin with `getPlugin` afterwards. */
    purgeGrant(identifier: string, grantId: number, verificationPhrase: string): Observable<PluginGrant> {
        return this.api.purgeGrant(identifier, grantId, verificationPhrase);
    }

    listOrgRemovedJobs(
        identifier: string,
        query: PluginOrgRemovedJobQuery
    ): Observable<ApiGetRequest<PluginOrgRemovedJob>> {
        return this.api.listOrgRemovedJobs(identifier, query);
    }

    retryOrgRemovedJob(identifier: string, jobId: number): Observable<PluginOrgRemovedJob> {
        return this.api.retryOrgRemovedJob(identifier, jobId);
    }

    skipOrgRemovedJob(identifier: string, jobId: number): Observable<PluginOrgRemovedJob> {
        return this.api.skipOrgRemovedJob(identifier, jobId);
    }

    getSettings(identifier: string): Observable<PluginSettingsResponse> {
        return this.api.getSettings(identifier);
    }

    updateSettings(identifier: string, update: PluginSettingsUpdate): Observable<PluginSettingsResponse> {
        return this.api.updateSettings(identifier, update);
    }

    getLimits(identifier: string): Observable<PluginLimitsResponse> {
        return this.api.getLimits(identifier);
    }

    updateLimits(identifier: string, update: PluginLimitsUpdate): Observable<PluginLimitsResponse> {
        return this.api.updateLimits(identifier, update);
    }

    getRuntime(identifier: string): Observable<PluginRuntimeResponse> {
        return this.api.getRuntime(identifier);
    }

    /** A restart can move the plugin's state (`failed` → `provisioning`): reload it with `getPlugin` afterwards. */
    restart(identifier: string): Observable<PluginRuntimeResponse> {
        return this.api.restart(identifier);
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
        purge_after: plugin.purge_after,
        needs_attention: plugin.needs_attention,
    };
}

function byName(first: PluginSummary, second: PluginSummary): number {
    return first.name.localeCompare(second.name) || first.identifier.localeCompare(second.identifier);
}
