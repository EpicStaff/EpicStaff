import { HttpClient } from '@angular/common/http';
import { Injectable } from '@angular/core';
import { Observable } from 'rxjs';
import { map } from 'rxjs/operators';
import { ApiGetRequest } from '../../../core/models/api-request.model';
import {
  RealtimeAgent,
  UpdateRealtimeAgentRequest,
} from '../models/realtime-agent.model';
import { ConfigService } from '../../../services/config/config.service';

@Injectable({
  providedIn: 'root',
})
export class RealtimeAgentService {
  constructor(private http: HttpClient, private configService: ConfigService) {}

  // Dynamically retrieve the API URL from ConfigService
  private get apiUrl(): string {
    return this.configService.apiUrl + 'realtime-agents/';
  }

  /**
   * Get all realtime agents
   * @returns Observable of RealtimeAgent array
   */
  getRealtimeAgents(): Observable<RealtimeAgent[]> {
    return this.http
      .get<ApiGetRequest<RealtimeAgent>>(this.apiUrl)
      .pipe(map((response: ApiGetRequest<RealtimeAgent>) => response.results));
  }

  getRealtimeAgentById(id: number): Observable<RealtimeAgent> {
    const url: string = `${this.apiUrl}${id}/`;
    return this.http.get<RealtimeAgent>(url);
  }

  updateRealtimeAgent(
    agentId: string,
    agentData: UpdateRealtimeAgentRequest
  ): Observable<RealtimeAgent> {
    const url: string = `${this.apiUrl}${agentId}/`;
    return this.http.put<RealtimeAgent>(url, agentData);
  }

  createRealtimeAgent(
    agentData: UpdateRealtimeAgentRequest
  ): Observable<RealtimeAgent> {
    return this.http.post<RealtimeAgent>(this.apiUrl, agentData);
  }
}
