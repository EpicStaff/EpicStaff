import { HttpClient } from '@angular/common/http';
import { Injectable } from '@angular/core';
import { Observable, throwError } from 'rxjs';
import { catchError, map } from 'rxjs/operators';

import { ConfigService } from '../../services/config/config.service';

export interface EnvironmentKeysResponse {
    data: { [key: string]: string };
}

export interface EnvironmentKey {
    key: string;
    value: string;
}

@Injectable({
    providedIn: 'root',
})
export class EnvironmentKeysService {
    constructor(
        private http: HttpClient,
        private configService: ConfigService
    ) {}

    // Dynamically retrieve the API URL from ConfigService
    private get apiUrl(): string {
        return this.configService.apiUrl + 'environment/config/';
    }

    // Fetch all environment keys
    public getEnvironmentKeys(): Observable<{ [key: string]: string }> {
        return this.http.get<EnvironmentKeysResponse>(this.apiUrl).pipe(
            map((response: EnvironmentKeysResponse) => response.data),
            catchError((error) => {
                console.error('Error fetching environment keys:', error);
                return throwError(() => error);
            })
        );
    }

    // Add or update an environment key
    public addOrUpdateEnvironmentKey(key: EnvironmentKey): Observable<{ success: boolean }> {
        const body = {
            data: {
                [key.key]: key.value,
            },
        };
        return this.http.post<{ success: boolean }>(this.apiUrl, body).pipe(
            catchError((error) => {
                console.error('Error adding/updating environment key:', error);
                return throwError(() => error);
            })
        );
    }

    // Delete an environment key
    public deleteEnvironmentKey(key: string): Observable<{ success: boolean }> {
        const encodedKey: string = encodeURIComponent(key);
        return this.http.delete<{ success: boolean }>(`${this.apiUrl}${encodedKey}/`).pipe(
            catchError((error) => {
                console.error('Error deleting environment key:', error);
                return throwError(() => error);
            })
        );
    }
}
