import { HttpClient, HttpHeaders } from '@angular/common/http';
import { Injectable } from '@angular/core';
import { Observable } from 'rxjs';
import { CreateLLMNodeRequest } from '../models/llm-node.model';
import { ConfigService } from '../../../../../services/config/config.service';

@Injectable({
  providedIn: 'root',
})
export class LLMNodeService {
  private headers = new HttpHeaders({
    'Content-Type': 'application/json',
  });

  constructor(private http: HttpClient, private configService: ConfigService) {}

  // Dynamically retrieve the API URL from ConfigService
  private get apiUrl(): string {
    return this.configService.apiUrl + 'llmnodes/';
  }

  createLLMNode(request: CreateLLMNodeRequest): Observable<any> {
    return this.http.post<any>(this.apiUrl, request, { headers: this.headers });
  }

  updateLLMNode(id: number, request: CreateLLMNodeRequest): Observable<any> {
    return this.http.put<any>(`${this.apiUrl}${id}/`, request, {
      headers: this.headers,
    });
  }

  deleteLLMNode(id: string): Observable<any> {
    return this.http.delete(`${this.apiUrl}${id}/`, { headers: this.headers });
  }
}
