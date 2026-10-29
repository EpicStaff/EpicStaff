import {
    HttpClient,
    HttpErrorResponse,
    HttpEvent,
    HttpEventType,
    HttpParams,
    HttpResponse,
} from '@angular/common/http';
import { inject, Injectable } from '@angular/core';
import { catchError, defer, filter, map, Observable, of, switchMap, throwError } from 'rxjs';

import { ApiGetRequest } from '../../../core/models/api-request.model';
import { ConfigService } from '../../../services/config';
import {
    PackageReview,
    PluginApproveRequest,
    PluginBackupList,
    PluginDetail,
    PluginGrant,
    PluginOrgRemovedJob,
    PluginOrgRemovedJobQuery,
    PluginRestore,
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
import { PluginDevelopment, PluginDevelopmentUpdate } from '../models/plugin-development.model';
import { PluginGrantPurgePreview, PluginPurgePreview } from '../models/plugin-purge-preview.model';
import { PluginSuspendPreview } from '../models/plugin-suspend-preview.model';

/** SuperAdmin plugin endpoints (`/api/admin/plugins/**`). Cross-org: the org interceptor sends no org header here. */
@Injectable({ providedIn: 'root' })
export class PluginsAdminApiService {
    private readonly http = inject(HttpClient);
    private readonly configService = inject(ConfigService);

    private get baseUrl(): string {
        return `${this.configService.apiUrl}admin/plugins/`;
    }

    listPlugins(): Observable<PluginSummary[]> {
        return this.http.get<PluginSummary[]>(this.baseUrl);
    }

    getPlugin(identifier: string): Observable<PluginDetail> {
        return this.http.get<PluginDetail>(this.pluginUrl(identifier));
    }

    /** Answers with the plugin `uninstalling` (409 `plugin_not_uninstallable` when its state does not allow it). */
    uninstallPlugin(identifier: string): Observable<PluginDetail> {
        return this.http.post<PluginDetail>(`${this.pluginUrl(identifier)}uninstall/`, null);
    }

    /** Answers with the plugin `provisioning`, or `running` without a backend (409 `plugin_not_uninstalling`). */
    reinstallPlugin(identifier: string): Observable<PluginDetail> {
        return this.http.post<PluginDetail>(`${this.pluginUrl(identifier)}reinstall/`, null);
    }

    /** What uninstalling or deleting the plugin affects. Read-only; answers in any state of the plugin. */
    getPluginPurgePreview(identifier: string): Observable<PluginPurgePreview> {
        return this.http.get<PluginPurgePreview>(`${this.pluginUrl(identifier)}purge-preview/`);
    }

    /** Starts deleting the plugin; answers 202 with it `purging`. The phrase is sent exactly as typed. */
    purgePlugin(identifier: string, verificationPhrase: string): Observable<PluginDetail> {
        return this.http.delete<PluginDetail>(this.pluginUrl(identifier), {
            body: { verification_phrase: verificationPhrase },
        });
    }

    /** Asks the node again to remove a plugin whose removal failed; answers 202. */
    retryRemoval(identifier: string): Observable<PluginDetail> {
        return this.http.post<PluginDetail>(`${this.pluginUrl(identifier)}retry-removal/`, null);
    }

    /** Uploads a `.esplugin` package: progress while the bytes go up, then the review of the stored package. */
    uploadPackage(file: File): Observable<PluginUploadEvent> {
        const body = new FormData();
        body.append('file', file, file.name);
        return this.http
            .post<PackageReview>(`${this.baseUrl}packages/`, body, { reportProgress: true, observe: 'events' })
            .pipe(
                map((event) => toUploadEvent(event)),
                filter((event): event is PluginUploadEvent => event !== null)
            );
    }

    getPackageReview(packageId: number): Observable<PackageReview> {
        return this.http.get<PackageReview>(`${this.baseUrl}packages/${packageId}/review/`);
    }

    /**
     * A first install answers 200 with the plugin installing; an upgrade answers 202 with its `open_upgrade`, or 200 when
     * it completed at once (a version that only changes the frontend).
     */
    approvePackage(packageId: number, request: PluginApproveRequest): Observable<PluginDetail> {
        return this.http.post<PluginDetail>(`${this.baseUrl}packages/${packageId}/approve/`, request);
    }

    /** Answers with the plugin back on its installed version (409 `upgrade_not_cancellable` otherwise). */
    cancelUpgrade(identifier: string): Observable<PluginDetail> {
        return this.http.post<PluginDetail>(`${this.pluginUrl(identifier)}upgrade/cancel/`, null);
    }

    /** Runs the failed stage of the open upgrade again; answers 202 (409 `upgrade_not_retryable` otherwise). */
    retryUpgrade(identifier: string): Observable<PluginDetail> {
        return this.http.post<PluginDetail>(`${this.pluginUrl(identifier)}upgrade/retry/`, null);
    }

    /** The backups the plugin node holds of the plugin's database, newest first. */
    listBackups(identifier: string): Observable<PluginBackupList> {
        return this.http.get<PluginBackupList>(`${this.pluginUrl(identifier)}backups/`);
    }

    /** Asks the node to restore a backup of the failed upgrade under way; answers 202. The phrase is sent as typed. */
    restoreBackup(identifier: string, backupId: number, verificationPhrase: string): Observable<PluginRestore> {
        return this.http.post<PluginRestore>(`${this.pluginUrl(identifier)}backups/${backupId}/restore/`, {
            verification_phrase: verificationPhrase,
        });
    }

    rejectPackage(packageId: number): Observable<void> {
        return this.http.post<void>(`${this.baseUrl}packages/${packageId}/reject/`, null);
    }

    /** One page of the plugin's grants, sorted by organization name. */
    listGrants(identifier: string, page: number, pageSize: number): Observable<ApiGetRequest<PluginGrant>> {
        const params = new HttpParams().set('page', String(page)).set('page_size', String(pageSize));
        return this.http.get<ApiGetRequest<PluginGrant>>(`${this.pluginUrl(identifier)}grants/`, { params });
    }

    createGrant(identifier: string, organizationId: number): Observable<PluginGrant> {
        return this.http.post<PluginGrant>(`${this.pluginUrl(identifier)}grants/`, { organization_id: organizationId });
    }

    /**
     * Runs a failed install or upgrade hook again; the grant answers back in `granting` or `upgrading` (409
     * `hook_not_retryable` otherwise).
     */
    retryHook(identifier: string, grantId: number): Observable<PluginGrant> {
        return this.http.post<PluginGrant>(`${this.grantUrl(identifier, grantId)}retry-hook/`, null);
    }

    /** What suspending the grant would stop in its organization. Read-only; answers in any state of the grant. */
    getSuspendPreview(identifier: string, grantId: number): Observable<PluginSuspendPreview> {
        return this.http.get<PluginSuspendPreview>(`${this.grantUrl(identifier, grantId)}suspend-preview/`);
    }

    /** Answers with the grant `suspended` (409 `grant_not_suspendable` when its state does not allow it). */
    suspendGrant(identifier: string, grantId: number): Observable<PluginGrant> {
        return this.http.post<PluginGrant>(`${this.grantUrl(identifier, grantId)}suspend/`, null);
    }

    /** Answers with the grant `active`, or `install_failed` when its install never finished (409 `grant_not_suspended`). */
    resumeGrant(identifier: string, grantId: number): Observable<PluginGrant> {
        return this.http.post<PluginGrant>(`${this.grantUrl(identifier, grantId)}resume/`, null);
    }

    /** What deleting the grant's data removes in its organization. Read-only; answers in any state of the grant. */
    getGrantPurgePreview(identifier: string, grantId: number): Observable<PluginGrantPurgePreview> {
        return this.http.get<PluginGrantPurgePreview>(`${this.grantUrl(identifier, grantId)}purge-preview/`);
    }

    /** Starts deleting the grant's data; answers 202 with the grant `purging`. The phrase is sent exactly as typed. */
    purgeGrant(identifier: string, grantId: number, verificationPhrase: string): Observable<PluginGrant> {
        return this.http.delete<PluginGrant>(this.grantUrl(identifier, grantId), {
            body: { verification_phrase: verificationPhrase },
        });
    }

    /** One page of the plugin's data removals, newest first. */
    listOrgRemovedJobs(
        identifier: string,
        query: PluginOrgRemovedJobQuery
    ): Observable<ApiGetRequest<PluginOrgRemovedJob>> {
        const params = new HttpParams()
            .set('state', query.state)
            .set('deleted_organizations', String(query.deletedOrganizations))
            .set('page', String(query.page))
            .set('page_size', String(query.pageSize));
        return this.http.get<ApiGetRequest<PluginOrgRemovedJob>>(`${this.pluginUrl(identifier)}org-removed-jobs/`, {
            params,
        });
    }

    /** Runs a data removal again now, with a new retry window; answers 202. */
    retryOrgRemovedJob(identifier: string, jobId: number): Observable<PluginOrgRemovedJob> {
        return this.http.post<PluginOrgRemovedJob>(`${this.orgRemovedJobUrl(identifier, jobId)}retry/`, null);
    }

    /** Gives up on a data removal: the plugin keeps that organization's data until the plugin is deleted. */
    skipOrgRemovedJob(identifier: string, jobId: number): Observable<PluginOrgRemovedJob> {
        return this.http.post<PluginOrgRemovedJob>(`${this.orgRemovedJobUrl(identifier, jobId)}skip/`, null);
    }

    /** The settings of a plugin with a backend (409 `plugin_has_no_backend` otherwise; so are the calls below). */
    getSettings(identifier: string): Observable<PluginSettingsResponse> {
        return this.http.get<PluginSettingsResponse>(`${this.pluginUrl(identifier)}settings/`);
    }

    /** Changes only the keys given; saving restarts the plugin. */
    updateSettings(identifier: string, update: PluginSettingsUpdate): Observable<PluginSettingsResponse> {
        return this.http.patch<PluginSettingsResponse>(`${this.pluginUrl(identifier)}settings/`, update);
    }

    getLimits(identifier: string): Observable<PluginLimitsResponse> {
        return this.http.get<PluginLimitsResponse>(`${this.pluginUrl(identifier)}limits/`);
    }

    /** Changes only the overrides given; the plugin restarts with the new limits. */
    updateLimits(identifier: string, update: PluginLimitsUpdate): Observable<PluginLimitsResponse> {
        return this.http.patch<PluginLimitsResponse>(`${this.pluginUrl(identifier)}limits/`, update);
    }

    getRuntime(identifier: string): Observable<PluginRuntimeResponse> {
        return this.http.get<PluginRuntimeResponse>(`${this.pluginUrl(identifier)}runtime/`);
    }

    /** Asks the node to restart the process; a failed plugin goes back to provisioning. Answers 202. */
    restart(identifier: string): Observable<PluginRuntimeResponse> {
        return this.http.post<PluginRuntimeResponse>(`${this.pluginUrl(identifier)}restart/`, null);
    }

    /** The plugin's development state; answers while development mode is off too. */
    getDevelopment(identifier: string): Observable<PluginDevelopment> {
        return this.http.get<PluginDevelopment>(this.developmentUrl(identifier));
    }

    /** Stores both ports (409 `plugin_development_mode_off` or `plugin_not_running`; 400 `invalid` by `loc`). */
    updateDevelopment(identifier: string, update: PluginDevelopmentUpdate): Observable<PluginDevelopment> {
        return this.http.put<PluginDevelopment>(this.developmentUrl(identifier), update);
    }

    /** Stop development: removes the target and stops the development keys. Answers 204, also with nothing stored. */
    clearDevelopment(identifier: string): Observable<void> {
        return this.http.delete<void>(this.developmentUrl(identifier));
    }

    /**
     * Issues new development keys and answers with the development runtime file, as the server sent it: the body is
     * for the browser's download only, never read here. A refusal's JSON error is read into the error as usual.
     */
    downloadDevelopmentRuntimeFile(identifier: string): Observable<HttpResponse<Blob>> {
        return this.http
            .post(`${this.developmentUrl(identifier)}runtime-file/`, null, {
                responseType: 'blob',
                observe: 'response',
            })
            .pipe(catchError((error: unknown) => throwWithJsonErrorBody(error)));
    }

    private pluginUrl(identifier: string): string {
        return `${this.baseUrl}${encodeURIComponent(identifier)}/`;
    }

    private grantUrl(identifier: string, grantId: number): string {
        return `${this.pluginUrl(identifier)}grants/${grantId}/`;
    }

    private orgRemovedJobUrl(identifier: string, jobId: number): string {
        return `${this.pluginUrl(identifier)}org-removed-jobs/${jobId}/`;
    }

    private developmentUrl(identifier: string): string {
        return `${this.pluginUrl(identifier)}development/`;
    }
}

/**
 * A refused blob request carries its JSON error body as a Blob. Rethrows the error with that body parsed (`null` when
 * it is not JSON), so `toPluginErrorView` reads its code as for any other request. Only a refusal's body is read.
 */
function throwWithJsonErrorBody(error: unknown): Observable<never> {
    if (!(error instanceof HttpErrorResponse) || !(error.error instanceof Blob)) return throwError(() => error);
    const body = error.error;
    return defer(() => body.text()).pipe(
        catchError(() => of('')),
        switchMap((text) =>
            throwError(
                () =>
                    new HttpErrorResponse({
                        error: parseJson(text),
                        headers: error.headers,
                        status: error.status,
                        statusText: error.statusText,
                        url: error.url ?? undefined,
                    })
            )
        )
    );
}

function parseJson(text: string): unknown {
    try {
        return JSON.parse(text) as unknown;
    } catch {
        return null;
    }
}

function toUploadEvent(event: HttpEvent<PackageReview>): PluginUploadEvent | null {
    if (event.type === HttpEventType.UploadProgress) {
        return { kind: 'progress', loaded: event.loaded, total: event.total ?? null };
    }
    if (event.type === HttpEventType.Response && event.body) {
        return { kind: 'done', review: event.body };
    }
    return null;
}
