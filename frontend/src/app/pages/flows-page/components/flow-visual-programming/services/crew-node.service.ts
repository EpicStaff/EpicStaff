import { HttpClient, HttpHeaders } from '@angular/common/http';
import { Injectable } from '@angular/core';
import { Observable } from 'rxjs';
import { CreateCrewNodeRequest } from '../models/crew-node.model';
import { ConfigService } from '../../../../../services/config/config.service';

@Injectable({
  providedIn: 'root',
})
export class CrewNodeService {
  private headers = new HttpHeaders({
    'Content-Type': 'application/json',
  });

  constructor(
    private http: HttpClient,
    private configService: ConfigService
  ) {}

  private get apiUrl(): string {
    return this.configService.apiUrl + 'crewnodes/';
  }

  createCrewNode(request: CreateCrewNodeRequest): Observable<any> {
    return this.http.post<any>(this.apiUrl, request, {
      headers: this.headers,
    });
  }

  updateCrewNode(id: number, request: CreateCrewNodeRequest): Observable<any> {
    return this.http.put<any>(`${this.apiUrl}${id}/`, request, {
      headers: this.headers,
    });
  }

  deleteCrewNode(id: string): Observable<any> {
    return this.http.delete(`${this.apiUrl}${id}/`, { headers: this.headers });
  }
}
