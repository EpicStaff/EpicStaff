import { HttpClient } from '@angular/common/http';
import { inject, Injectable } from '@angular/core';
import { ActionCode, CreateLabelRequest, LabelDto, PatchLabelRequest, ResourceCode, UpdateLabelRequest } from '@shared/models';
import { LabelsApi } from '@shared/services';
import { Observable } from 'rxjs';
import { map } from 'rxjs/operators';

import { withPermission } from '../../../core/http/permission-context';
import { ApiGetRequest } from '../../../core/models/api-request.model';
import { ConfigService } from '../../../services/config';

@Injectable({ providedIn: 'root' })
export class LabelsApiService implements LabelsApi {
    private http = inject(HttpClient);
    private configService = inject(ConfigService);

    private get apiUrl(): string {
        return `${this.configService.apiUrl}labels/`;
    }

    getLabels(): Observable<LabelDto[]> {
        return this.http
            .get<ApiGetRequest<LabelDto>>(this.apiUrl, {
                context: withPermission<ApiGetRequest<LabelDto>>(ResourceCode.Flows, ActionCode.Read, {
                    count: 0,
                    next: null,
                    previous: null,
                    results: [],
                }),
            })
            .pipe(map((response) => response.results));
    }

    createLabel(data: CreateLabelRequest): Observable<LabelDto> {
        return this.http.post<LabelDto>(this.apiUrl, data);
    }

    updateLabel(id: number, data: UpdateLabelRequest): Observable<LabelDto> {
        return this.http.put<LabelDto>(`${this.apiUrl}${id}/`, data);
    }

    patchLabel(id: number, data: PatchLabelRequest): Observable<LabelDto> {
        return this.http.patch<LabelDto>(`${this.apiUrl}${id}/`, data);
    }

    deleteLabel(id: number): Observable<void> {
        return this.http.delete<void>(`${this.apiUrl}${id}/`);
    }
}
