import { Injectable, inject } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';
import { ConfigService } from '../config/config.service';

export interface FirstSetupStatus {
  needs_setup: boolean;
}

export interface FirstSetupRequest {
  username: string;
  password: string;
  email?: string;
}

export interface FirstSetupResponse {
  access: string;
  refresh: string;
  api_key: string;
}

@Injectable({ providedIn: 'root' })
export class SetupService {
  private readonly http = inject(HttpClient);
  private readonly configService = inject(ConfigService);

  private get baseUrl(): string {
    return this.configService.apiUrl.replace(/\/+$/, '');
  }

  getStatus(): Observable<FirstSetupStatus> {
    return this.http.get<FirstSetupStatus>(`${this.baseUrl}/auth/first-setup/`);
  }

  runSetup(payload: FirstSetupRequest): Observable<FirstSetupResponse> {
    return this.http.post<FirstSetupResponse>(
      `${this.baseUrl}/auth/first-setup/`,
      payload
    );
  }
}
