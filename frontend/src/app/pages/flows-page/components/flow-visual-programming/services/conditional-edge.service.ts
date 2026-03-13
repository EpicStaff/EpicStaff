import { HttpClient, HttpHeaders } from '@angular/common/http';
import { Injectable } from '@angular/core';
import { Observable } from 'rxjs';
import {
  CreateConditionalEdgeRequest,
  GetConditionalEdgeRequest,
} from '../models/conditional-edge.model';
import { ConfigService } from '../../../../../services/config/config.service';

@Injectable({
  providedIn: 'root',
})
export class ConditionalEdgeService {
  private headers = new HttpHeaders({
    'Content-Type': 'application/json',
  });

  constructor(private http: HttpClient, private configService: ConfigService) {}

  // Dynamically retrieve the API URL from ConfigService
  private get apiUrl(): string {
    return this.configService.apiUrl + 'conditionaledges/';
  }

  createConditionalEdge(
    request: CreateConditionalEdgeRequest
  ): Observable<any> {
    return this.http.post<any>(this.apiUrl, request, {
      headers: this.headers,
    });
  }

  updateConditionalEdge(
    id: number,
    request: CreateConditionalEdgeRequest
  ): Observable<any> {
    return this.http.put<any>(`${this.apiUrl}${id}/`, request, {
      headers: this.headers,
    });
  }

  getConditionalEdgeById(id: number): Observable<GetConditionalEdgeRequest> {
    return this.http.get<GetConditionalEdgeRequest>(`${this.apiUrl}${id}/`, {
      headers: this.headers,
    });
  }

  deleteConditionalEdge(id: number): Observable<any> {
    return this.http.delete(`${this.apiUrl}${id}/`, { headers: this.headers });
  }
}
