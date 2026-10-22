import { HttpClient, HttpParams } from '@angular/common/http';
import { inject, Injectable } from '@angular/core';
import { ActionCode, ResourceCode } from '@shared/models';
import { map, Observable } from 'rxjs';

import { withPermission } from '../../../core/http/permission-context';
import { ConfigService } from '../../../services/config';
import { CreateVenvRequest, UpdateVenvRequest, Venv, VenvListResponse } from '../models/venv.model';

// The MVP list is client-side filtered; one high-limit page covers every venv an org owns.
const LIST_LIMIT = '1000';

@Injectable({ providedIn: 'root' })
export class VenvsApiService {
    private readonly http: HttpClient = inject(HttpClient);
    private readonly configService: ConfigService = inject(ConfigService);

    private get venvsUrl(): string {
        return `${this.configService.apiUrl}venvs/`;
    }

    getVenvs(): Observable<Venv[]> {
        const params = new HttpParams().set('limit', LIST_LIMIT);
        return this.http
            .get<VenvListResponse>(this.venvsUrl, {
                params,
                context: withPermission<VenvListResponse>(ResourceCode.Venvs, ActionCode.Read, {
                    count: 0,
                    limit: 0,
                    offset: 0,
                    next: null,
                    previous: null,
                    result: [],
                }),
            })
            .pipe(map((response) => response.result));
    }

    getVenv(id: number): Observable<Venv> {
        return this.http.get<Venv>(`${this.venvsUrl}${id}/`);
    }

    createVenv(body: CreateVenvRequest): Observable<Venv> {
        return this.http.post<Venv>(this.venvsUrl, body);
    }

    updateVenv(id: number, body: UpdateVenvRequest): Observable<Venv> {
        return this.http.patch<Venv>(`${this.venvsUrl}${id}/`, body);
    }

    deleteVenv(id: number): Observable<void> {
        return this.http.delete<void>(`${this.venvsUrl}${id}/`);
    }
}
