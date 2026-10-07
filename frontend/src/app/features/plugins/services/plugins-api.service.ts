import { HttpClient, HttpEvent, HttpEventType } from '@angular/common/http';
import { inject, Injectable } from '@angular/core';
import { ActionCode, ResourceCode } from '@shared/models';
import { filter, map, Observable } from 'rxjs';

import { withPermission } from '../../../core/http/permission-context';
import { ConfigService } from '../../../services/config';
import {
    PluginDeletePreview,
    PluginDetail,
    PluginDevUiRequest,
    PluginInspectResult,
    PluginInstallEvent,
    PluginNavItem,
    PluginSecretsRequest,
    PluginSecretValues,
    PluginSummary,
    PluginUiSession,
} from '../models/plugin.model';

/** Maps one `install` HTTP event to an install event; `null` for events the caller doesn't need. */
export function toPluginInstallEvent(event: HttpEvent<PluginDetail>): PluginInstallEvent | null {
    if (event.type === HttpEventType.UploadProgress) {
        const percent = event.total ? Math.round((event.loaded / event.total) * 100) : 0;
        return { kind: 'progress', percent: Math.min(100, Math.max(0, percent)) };
    }
    if (event.type === HttpEventType.Response && event.body) {
        return { kind: 'done', plugin: event.body };
    }
    return null;
}

@Injectable({ providedIn: 'root' })
export class PluginsApiService {
    private readonly http = inject(HttpClient);
    private readonly configService = inject(ConfigService);

    private get baseUrl(): string {
        return `${this.configService.apiUrl}plugins/`;
    }

    /** Plain array, ordered by name. Short-circuits to `[]` for a role without `plugins:read`. */
    list(): Observable<PluginSummary[]> {
        return this.http.get<PluginSummary[]>(this.baseUrl, {
            context: withPermission<PluginSummary[]>(ResourceCode.Plugins, ActionCode.Read, []),
        });
    }

    /** The navigation buttons. Short-circuits to `[]` for a role without `plugins:use`. */
    listNav(): Observable<PluginNavItem[]> {
        return this.http.get<PluginNavItem[]>(`${this.baseUrl}nav/`, {
            context: withPermission<PluginNavItem[]>(ResourceCode.Plugins, ActionCode.Use, []),
        });
    }

    get(id: number): Observable<PluginDetail> {
        return this.http.get<PluginDetail>(`${this.baseUrl}${id}/`);
    }

    /** Validates a plugin file and returns the review step's data. Writes nothing. */
    inspect(file: File): Observable<PluginInspectResult> {
        const body = new FormData();
        body.append('file', file);
        return this.http.post<PluginInspectResult>(`${this.baseUrl}inspect/`, body);
    }

    /** Uploads and installs a plugin: emits upload progress (0–100), then the installed plugin. */
    install(file: File, secrets: PluginSecretValues): Observable<PluginInstallEvent> {
        const body = new FormData();
        body.append('file', file);
        // The contract requires `secrets` only when the plugin declares slots.
        if (Object.keys(secrets).length > 0) {
            body.append('secrets', JSON.stringify(secrets));
        }
        return this.http
            .post<PluginDetail>(`${this.baseUrl}install/`, body, { reportProgress: true, observe: 'events' })
            .pipe(
                map(toPluginInstallEvent),
                filter((event): event is PluginInstallEvent => event !== null)
            );
    }

    suspend(id: number): Observable<PluginDetail> {
        return this.http.post<PluginDetail>(`${this.baseUrl}${id}/suspend/`, null);
    }

    resume(id: number): Observable<PluginDetail> {
        return this.http.post<PluginDetail>(`${this.baseUrl}${id}/resume/`, null);
    }

    retry(id: number): Observable<PluginDetail> {
        return this.http.post<PluginDetail>(`${this.baseUrl}${id}/retry/`, null);
    }

    updateSecrets(id: number, request: PluginSecretsRequest): Observable<PluginDetail> {
        return this.http.post<PluginDetail>(`${this.baseUrl}${id}/secrets/`, request);
    }

    getDeletePreview(id: number): Observable<PluginDeletePreview> {
        return this.http.get<PluginDeletePreview>(`${this.baseUrl}${id}/delete-preview/`);
    }

    delete(id: number): Observable<void> {
        return this.http.delete<void>(`${this.baseUrl}${id}/`);
    }

    createUiSession(id: number): Observable<PluginUiSession> {
        return this.http.post<PluginUiSession>(`${this.baseUrl}${id}/ui-session/`, null);
    }

    /** Dev mode: loads this plugin's page from `url` (a localhost dev server), for the caller only. */
    setDevUi(id: number, url: string): Observable<PluginDetail> {
        const body: PluginDevUiRequest = { url };
        return this.http.post<PluginDetail>(`${this.baseUrl}${id}/dev-ui/`, body);
    }

    /** Dev mode off for this plugin: everyone gets the installed page again. */
    clearDevUi(id: number): Observable<PluginDetail> {
        return this.http.delete<PluginDetail>(`${this.baseUrl}${id}/dev-ui/`);
    }
}
