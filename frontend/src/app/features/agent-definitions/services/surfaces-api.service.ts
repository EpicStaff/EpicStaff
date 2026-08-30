import { HttpClient, HttpHeaders, HttpParams } from '@angular/common/http';
import { inject, Injectable } from '@angular/core';
import { map, Observable } from 'rxjs';

import { ApiGetRequest } from '../../../core/models/api-request.model';
import { ConfigService } from '../../../services/config/config.service';
import {
    CombinedSurface,
    CreateSurfaceRequest,
    PartialUpdateSurfaceRequest,
    Surface,
    UpdateSurfaceRequest,
} from '../models/surface.model';

@Injectable({ providedIn: 'root' })
export class SurfacesApiService {
    private readonly http: HttpClient = inject(HttpClient);
    private readonly configService: ConfigService = inject(ConfigService);

    private readonly httpHeaders = new HttpHeaders({ 'Content-Type': 'application/json' });

    private get baseUrl(): string {
        return `${this.configService.apiUrl}surfaces/`;
    }

    getSurfaces(): Observable<Surface[]> {
        const params = new HttpParams().set('limit', '1000');
        return this.http.get<ApiGetRequest<Surface>>(this.baseUrl, { params }).pipe(map((res) => res.results));
    }

    getById(id: number): Observable<Surface> {
        return this.http.get<Surface>(`${this.baseUrl}${id}/`, { headers: this.httpHeaders });
    }

    create(body: CreateSurfaceRequest): Observable<Surface> {
        return this.http.post<Surface>(this.baseUrl, body, { headers: this.httpHeaders });
    }

    update(id: number, body: UpdateSurfaceRequest): Observable<Surface> {
        return this.http.put<Surface>(`${this.baseUrl}${id}/`, body, { headers: this.httpHeaders });
    }

    partialUpdate(id: number, body: PartialUpdateSurfaceRequest): Observable<Surface> {
        return this.http.patch<Surface>(`${this.baseUrl}${id}/`, body, { headers: this.httpHeaders });
    }

    delete(id: number): Observable<void> {
        return this.http.delete<void>(`${this.baseUrl}${id}/`, { headers: this.httpHeaders });
    }

    combine(surfaceIds: number[]): Observable<CombinedSurface> {
        return this.http.post<CombinedSurface>(
            `${this.baseUrl}combine/`,
            { surface_ids: surfaceIds },
            { headers: this.httpHeaders }
        );
    }
}
