import { HttpClient } from '@angular/common/http';
import { inject, Injectable } from '@angular/core';
import { FlowEditorPreferences } from '@shared/models';
import { map, Observable } from 'rxjs';

import { ConfigService } from '../../services/config';

/** The settings one user overrides for one flow; the keys left out follow the account. */
export interface FlowViewOverride extends Partial<FlowEditorPreferences> {
    /** IANA zone new schedule triggers in this flow open with; left out, the account's default timezone is used. */
    readonly default_timezone?: string;
}

interface FlowViewSettingsDto {
    settings: FlowViewOverride;
}

/** `/api/graphs/<id>/my-view-settings/`: the signed-in user's own view settings for one flow. */
@Injectable({ providedIn: 'root' })
export class FlowViewSettingsApiService {
    private readonly http = inject(HttpClient);
    private readonly configService = inject(ConfigService);

    get(graphId: number): Observable<FlowViewOverride> {
        return this.http.get<FlowViewSettingsDto>(this.url(graphId)).pipe(map((response) => response.settings));
    }

    /** Replaces the whole override of the flow. */
    put(graphId: number, settings: FlowViewOverride): Observable<FlowViewOverride> {
        return this.http
            .put<FlowViewSettingsDto>(this.url(graphId), { settings })
            .pipe(map((response) => response.settings));
    }

    delete(graphId: number): Observable<void> {
        return this.http.delete<void>(this.url(graphId));
    }

    private url(graphId: number): string {
        return `${this.configService.apiUrl}graphs/${graphId}/my-view-settings/`;
    }
}
