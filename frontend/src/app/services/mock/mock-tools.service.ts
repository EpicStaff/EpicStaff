import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';
import { Tool } from '../../features/tools/models/tool.model';

@Injectable({
  providedIn: 'root',
})
export class MockToolService {
  private apiBaseUrl = 'http://127.0.0.1:8000/api/tools/';

  constructor(private http: HttpClient) {}

  // Method to fetch all tools
  getTools(): Observable<Tool[]> {
    console.log(`GET request to: ${this.apiBaseUrl}`);
    return this.http.get<Tool[]>(this.apiBaseUrl);
  }

  // Method to fetch a tool by ID
  getToolById(id: number): Observable<Tool | null> {
    const url = `${this.apiBaseUrl}${id}/`;
    console.log(`GET request to: ${url}`);
    return this.http.get<Tool | null>(url);
  }
}
