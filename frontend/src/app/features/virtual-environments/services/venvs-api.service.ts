import { HttpClient, HttpParams } from '@angular/common/http';
import { inject, Injectable } from '@angular/core';
import { ActionCode, ResourceCode } from '@shared/models';
import { map, Observable } from 'rxjs';

import { withPermission } from '../../../core/http/permission-context';
import { ConfigService } from '../../../services/config';
import { CreateVenvRequest, UpdateVenvRequest, Venv, VenvListQuery, VenvListResponse } from '../models/venv.model';

const LIST_LIMIT = '1000';

@Injectable({ providedIn: 'root' })
export class VenvsApiService {
    private readonly http: HttpClient = inject(HttpClient);
    private readonly configService: ConfigService = inject(ConfigService);

    private get venvsUrl(): string {
        return `${this.configService.apiUrl}venvs/`;
    }

    getVenvs(query: VenvListQuery = {}): Observable<Venv[]> {
        let params = new HttpParams().set('limit', LIST_LIMIT);
        if (query.search) params = params.set('search', query.search);
        if (query.order) params = params.set('order', query.order);
        // Only the narrowing is a filter; 'false' would mean the same as no filter at all.
        if (query.isFavorite) params = params.set('is_favorite', 'true');
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

    /** Mark the venv as this user's favorite, or take the mark off again. */
    setFavorite(id: number, favorite: boolean): Observable<void> {
        const url = `${this.venvsUrl}${id}/favorite/`;
        return favorite ? this.http.post<void>(url, null) : this.http.delete<void>(url);
    }

    deleteVenv(id: number): Observable<void> {
        return this.http.delete<void>(`${this.venvsUrl}${id}/`);
    }
}
