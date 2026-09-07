import { HttpClient, HttpHeaders } from '@angular/common/http';
import { Injectable } from '@angular/core';
import { CreateLabelRequest, LabelDto, PatchLabelRequest, UpdateLabelRequest } from '@shared/models';
import { LabelsApi } from '@shared/services';
import { map, Observable } from 'rxjs';

import { ApiGetRequest } from '../../../core/models/api-request.model';
import { ConfigService } from '../../../services/config';

@Injectable({ providedIn: 'root' })
export class ToolsLabelsService implements LabelsApi {
    private headers = new HttpHeaders({ 'Content-Type': 'application/json' });

    constructor(
        private http: HttpClient,
        private configService: ConfigService
    ) {}

    private get baseUrl(): string {
        return this.configService.apiUrl + 'tool-labels/';
    }

    getLabels(): Observable<LabelDto[]> {
        return this.http.get<ApiGetRequest<LabelDto>>(this.baseUrl).pipe(map((response) => response.results));
    }

    createLabel(body: CreateLabelRequest): Observable<LabelDto> {
        return this.http.post<LabelDto>(this.baseUrl, body, { headers: this.headers });
    }

    updateLabel(labelId: number, body: UpdateLabelRequest): Observable<LabelDto> {
        return this.http.put<LabelDto>(`${this.baseUrl}${labelId}/`, body, { headers: this.headers });
    }

    patchLabel(labelId: number, body: PatchLabelRequest): Observable<LabelDto> {
        return this.http.patch<LabelDto>(`${this.baseUrl}${labelId}/`, body, { headers: this.headers });
    }

    deleteLabel(labelId: number): Observable<void> {
        return this.http.delete<void>(`${this.baseUrl}${labelId}/`, { headers: this.headers });
    }
}
