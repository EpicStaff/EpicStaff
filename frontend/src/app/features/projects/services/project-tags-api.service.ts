import { HttpClient, HttpHeaders } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';
import { map } from 'rxjs/operators';
import { ConfigService } from '../../../services/config/config.service';
import { ApiGetRequest } from '../../../core/models/api-request.model';
import {
  GetCrewTagRequest,
  CreateCrewTagRequest,
  UpdateCrewTagRequest,
} from '../models/crew-tag.model';

@Injectable({
  providedIn: 'root',
})
export class ProjectTagsApiService {
  private readonly configService = inject(ConfigService);
  private readonly http = inject(HttpClient);

  private readonly httpHeaders = new HttpHeaders({
    'Content-Type': 'application/json',
  });

  private get apiUrl(): string {
    return this.configService.apiUrl + 'crew-tags/';
  }

  // Get all crew tags
  getCrewTags(): Observable<GetCrewTagRequest[]> {
    return this.http
      .get<ApiGetRequest<GetCrewTagRequest>>(this.apiUrl)
      .pipe(map((response) => response.results));
  }

  // Get crew tag by ID
  getCrewTagById(id: number): Observable<GetCrewTagRequest> {
    return this.http.get<GetCrewTagRequest>(`${this.apiUrl}${id}/`);
  }

  // Create new crew tag
  createCrewTag(tag: CreateCrewTagRequest): Observable<GetCrewTagRequest> {
    return this.http.post<GetCrewTagRequest>(this.apiUrl, tag, {
      headers: this.httpHeaders,
    });
  }

  // Update crew tag
  updateCrewTag(
    id: number,
    tag: UpdateCrewTagRequest
  ): Observable<GetCrewTagRequest> {
    return this.http.put<GetCrewTagRequest>(`${this.apiUrl}${id}/`, tag, {
      headers: this.httpHeaders,
    });
  }

  // Partial update crew tag
  patchUpdateCrewTag(
    id: number,
    updateData: Partial<UpdateCrewTagRequest>
  ): Observable<GetCrewTagRequest> {
    return this.http.patch<GetCrewTagRequest>(
      `${this.apiUrl}${id}/`,
      updateData,
      {
        headers: this.httpHeaders,
      }
    );
  }

  // Delete crew tag
  deleteCrewTag(id: number): Observable<void> {
    return this.http.delete<void>(`${this.apiUrl}${id}/`, {
      headers: this.httpHeaders,
    });
  }
}
