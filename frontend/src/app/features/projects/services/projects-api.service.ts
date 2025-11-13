import { HttpClient, HttpHeaders } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';
import { map } from 'rxjs/operators';
import { ConfigService } from '../../../services/config/config.service';
import { ApiGetRequest } from '../../../shared/models/api-request.model';
import {
  GetProjectRequest,
  CreateProjectRequest,
  UpdateProjectRequest,
} from '../models/project.model';

@Injectable({
  providedIn: 'root',
})
export class ProjectsApiService {
  private readonly configService = inject(ConfigService);
  private readonly http = inject(HttpClient);

  private readonly httpHeaders = new HttpHeaders({
    'Content-Type': 'application/json',
  });

  private get apiUrl(): string {
    return this.configService.apiUrl + 'crews/';
  }

  getProjects(): Observable<GetProjectRequest[]> {
    return this.http
      .get<ApiGetRequest<GetProjectRequest>>(this.apiUrl)
      .pipe(map((response) => response.results));
  }

  getProjectById(id: number): Observable<GetProjectRequest> {
    return this.http.get<GetProjectRequest>(`${this.apiUrl}${id}/`);
  }

  createProject(project: CreateProjectRequest): Observable<GetProjectRequest> {
    return this.http.post<GetProjectRequest>(this.apiUrl, project, {
      headers: this.httpHeaders,
    });
  }

  updateProject(project: UpdateProjectRequest): Observable<GetProjectRequest> {
    return this.http.put<GetProjectRequest>(
      `${this.apiUrl}${project.id}/`,
      project,
      {
        headers: this.httpHeaders,
      }
    );
  }

  patchUpdateProject(
    id: number,
    updateData: Partial<GetProjectRequest>
  ): Observable<GetProjectRequest> {
    return this.http.patch<GetProjectRequest>(
      `${this.apiUrl}${id}/`,
      updateData,
      {
        headers: this.httpHeaders,
      }
    );
  }

  deleteProject(id: number): Observable<void> {
    return this.http.delete<void>(`${this.apiUrl}${id}/`, {
      headers: this.httpHeaders, // DELETE requests can also have headers if needed by API
    });
  }

  copyProject(id: number): Observable<GetProjectRequest> {
    return this.http.post<GetProjectRequest>(`${this.apiUrl}${id}/copy/`, id, {
      headers: this.httpHeaders,
    });
  }
}
