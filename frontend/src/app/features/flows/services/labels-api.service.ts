import { HttpClient } from '@angular/common/http';
import { inject, Injectable } from '@angular/core';
import { Observable } from 'rxjs';
import { map } from 'rxjs/operators';

import { ApiGetRequest } from '../../../core/models/api-request.model';
import { ConfigService } from '../../../services/config/config.service';
import { CreateLabelRequest, LabelDto, UpdateLabelRequest } from '../models/label.model';

@Injectable({ providedIn: 'root' })
export class LabelsApiService {
    private http = inject(HttpClient);
    private configService = inject(ConfigService);

    private get apiUrl(): string {
        return `${this.configService.apiUrl}labels/`;
    }

    getLabels(): Observable<LabelDto[]> {
        return this.http.get<ApiGetRequest<LabelDto>>(this.apiUrl).pipe(map((response) => response.results));
    }

    createLabel(data: CreateLabelRequest): Observable<LabelDto> {
        return this.http.post<LabelDto>(this.apiUrl, data);
    }

    updateLabel(id: number, data: UpdateLabelRequest): Observable<LabelDto> {
        return this.http.put<LabelDto>(`${this.apiUrl}${id}/`, data);
    }

    deleteLabel(id: number): Observable<void> {
        return this.http.delete<void>(`${this.apiUrl}${id}/`);
    }
}
