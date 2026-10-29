import { HttpClient, HttpHeaders } from '@angular/common/http';
import { inject, Injectable } from '@angular/core';
import { CreateLabelRequest, LabelDto, PatchLabelRequest } from '@shared/models';
import { LabelsApi } from '@shared/services';
import { map, Observable } from 'rxjs';

import { ApiGetRequest } from '../../../core/models/api-request.model';
import { ConfigService } from '../../../services/config';

/**
 * Groups of agents and shared surfaces. The backend stores them as flat labels on `agent-labels/`
 * (one label set shared by both kinds of item); the UI calls them groups.
 */
@Injectable({ providedIn: 'root' })
export class AgentGroupsApiService implements LabelsApi {
    private readonly http = inject(HttpClient);
    private readonly configService = inject(ConfigService);
    private readonly headers = new HttpHeaders({ 'Content-Type': 'application/json' });

    private get baseUrl(): string {
        return this.configService.apiUrl + 'agent-labels/';
    }

    getLabels(): Observable<LabelDto[]> {
        return this.http.get<ApiGetRequest<LabelDto>>(this.baseUrl).pipe(map((response) => response.results));
    }

    createLabel(body: CreateLabelRequest): Observable<LabelDto> {
        return this.http.post<LabelDto>(this.baseUrl, body, { headers: this.headers });
    }

    patchLabel(labelId: number, body: PatchLabelRequest): Observable<LabelDto> {
        return this.http.patch<LabelDto>(`${this.baseUrl}${labelId}/`, body, { headers: this.headers });
    }

    deleteLabel(labelId: number): Observable<void> {
        return this.http.delete<void>(`${this.baseUrl}${labelId}/`, { headers: this.headers });
    }
}
