import { HttpClient, HttpHeaders } from '@angular/common/http';
import { Injectable } from '@angular/core';
import { Observable } from 'rxjs';
import { CreatePythonNodeRequest } from '../models/python-node.model';
import { ConfigService } from '../../../../../services/config/config.service';

@Injectable({
  providedIn: 'root',
})
export class PythonNodeService {
  private headers = new HttpHeaders({
    'Content-Type': 'application/json',
  });

  constructor(private http: HttpClient, private configService: ConfigService) {}

  // Dynamically retrieve the API URL from ConfigService
  private get apiUrl(): string {
    return this.configService.apiUrl + 'pythonnodes/';
  }

  createPythonNode(request: CreatePythonNodeRequest): Observable<any> {
    return this.http.post<any>(this.apiUrl, request, {
      headers: this.headers,
    });
  }

  updatePythonNode(
    id: number,
    request: CreatePythonNodeRequest
  ): Observable<any> {
    return this.http.put<any>(`${this.apiUrl}${id}/`, request, {
      headers: this.headers,
    });
  }

  deletePythonNode(id: string): Observable<any> {
    return this.http.delete(`${this.apiUrl}${id}/`, {
      headers: this.headers,
    });
  }
}
