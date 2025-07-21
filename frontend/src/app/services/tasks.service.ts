import { HttpClient, HttpHeaders } from '@angular/common/http';
import { Injectable } from '@angular/core';
import { map, Observable } from 'rxjs';
import {
  CreateTaskRequest,
  GetTaskRequest,
  UpdateTaskRequest,
} from '../shared/models/task.model';
import { ApiGetRequest } from '../shared/models/api-request.model';
import { ConfigService } from './config/config.service';

@Injectable({
  providedIn: 'root',
})
export class TasksService {
  private headers = new HttpHeaders({ 'Content-Type': 'application/json' });

  constructor(private http: HttpClient, private configService: ConfigService) {}

  private get apiUrl(): string {
    return this.configService.apiUrl + 'tasks/';
  }

  getTasks(): Observable<GetTaskRequest[]> {
    const url = `${this.apiUrl}?limit=1000`;
    return this.http
      .get<ApiGetRequest<GetTaskRequest>>(url)
      .pipe(map((response) => response.results));
  }

  getTasksByProjectId(projectId: string): Observable<GetTaskRequest[]> {
    const url = `${this.apiUrl}?crew=${projectId}`;
    return this.http
      .get<ApiGetRequest<GetTaskRequest>>(url)
      .pipe(map((response) => response.results));
  }

  // GET task by ID
  getTaskById(taskId: number): Observable<GetTaskRequest> {
    return this.http.get<GetTaskRequest>(`${this.apiUrl}${taskId}/`);
  }

  createTask(task: CreateTaskRequest): Observable<GetTaskRequest> {
    return this.http.post<GetTaskRequest>(this.apiUrl, task, {
      headers: this.headers,
    });
  }

  updateTask(task: UpdateTaskRequest): Observable<GetTaskRequest> {
    return this.http.put<GetTaskRequest>(`${this.apiUrl}${task.id}/`, task, {
      headers: this.headers,
    });
  }

  // PATCH method to update task order
  patchTaskOrder(taskId: number, order: number): Observable<GetTaskRequest> {
    return this.http.patch<GetTaskRequest>(
      `${this.apiUrl}${taskId}/`,
      { order },
      {
        headers: this.headers,
      }
    );
  }

  // DELETE task
  deleteTask(taskId: number): Observable<void> {
    return this.http.delete<void>(`${this.apiUrl}${taskId}/`, {
      headers: this.headers,
    });
  }
}
