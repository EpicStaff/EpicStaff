import { HttpClient, HttpHeaders } from '@angular/common/http';
import { Injectable } from '@angular/core';
import { Observable } from 'rxjs';
import { CreateEdgeRequest } from '../models/edge.model';
import { ConfigService } from '../../../../../services/config/config.service';

@Injectable({
  providedIn: 'root',
})
export class EdgeService {
  private headers = new HttpHeaders({
    'Content-Type': 'application/json',
  });

  constructor(private http: HttpClient, private configService: ConfigService) {}

  // Dynamically retrieve the API URL from ConfigService
  private get apiUrl(): string {
    return this.configService.apiUrl + 'edges/';
  }

  createEdge(request: CreateEdgeRequest): Observable<any> {
    return this.http.post<any>(this.apiUrl, request, {
      headers: this.headers,
    });
  }

  updateEdge(id: number, request: CreateEdgeRequest): Observable<any> {
    return this.http.put<any>(`${this.apiUrl}${id}/`, request, {
      headers: this.headers,
    });
  }

  deleteEdge(id: number): Observable<any> {
    const url = `${this.apiUrl}${id}/`;
    return this.http.delete<any>(url, {
      headers: this.headers,
    });
  }
}
