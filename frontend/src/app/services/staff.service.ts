import { HttpClient, HttpHeaders } from '@angular/common/http';
import { Injectable } from '@angular/core';
import { forkJoin, map, Observable } from 'rxjs';
import {
  Agent,
  CreateAgentRequest,
  GetAgentRequest,
  UpdateAgentRequest,
} from '../shared/models/agent.model';
import { ApiGetRequest } from '../shared/models/api-request.model';
import { GetProjectRequest } from '../features/projects/models/project.model';
import { ConfigService } from './config/config.service';

@Injectable({
  providedIn: 'root',
})
export class AgentsService {
  private headers = new HttpHeaders({
    'Content-Type': 'application/json',
  });

  constructor(private http: HttpClient, private configService: ConfigService) {}

  // Dynamically retrieve the API URL from ConfigService
  private get apiUrl(): string {
    return this.configService.apiUrl + 'agents/';
  }

  // GET all agents
  getAgents(): Observable<GetAgentRequest[]> {
    const url = this.apiUrl;
    return this.http
      .get<ApiGetRequest<GetAgentRequest>>(url)
      .pipe(map((response) => response.results));
  }

  // GET agents by project (crew) ID
  getAgentsByProjectId(projectId: number): Observable<GetAgentRequest[]> {
    const url = `${this.apiUrl}?crew_id=${projectId}`;
    return this.http
      .get<ApiGetRequest<GetAgentRequest>>(url)
      .pipe(map((response) => response.results));
  }

  getAgentById(agentId: number): Observable<GetAgentRequest> {
    return this.http.get<GetAgentRequest>(`${this.apiUrl}${agentId}/`);
  }

  // POST create agent
  createAgent(agent: CreateAgentRequest): Observable<GetAgentRequest> {
    return this.http.post<GetAgentRequest>(this.apiUrl, agent, {
      headers: this.headers,
    });
  }

  // PUT update agent
  updateAgent(agent: UpdateAgentRequest): Observable<UpdateAgentRequest> {
    return this.http.put<UpdateAgentRequest>(
      `${this.apiUrl}${agent.id}/`,
      agent,
      {
        headers: this.headers,
      }
    );
  }

  // DELETE agent
  deleteAgent(agentId: number): Observable<void> {
    return this.http.delete<void>(`${this.apiUrl}${agentId}/`, {
      headers: this.headers,
    });
  }
}
