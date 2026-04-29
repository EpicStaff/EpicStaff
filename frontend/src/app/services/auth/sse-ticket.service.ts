import { HttpClient } from '@angular/common/http';
import { inject, Injectable } from '@angular/core';
import { catchError, Observable, switchMap, throwError } from 'rxjs';

import { ConfigService } from '../config';
import { AuthService } from './auth.service';

interface SseTicketResponse {
    ticket: string;
    expires_in: number;
}

@Injectable({ providedIn: 'root' })
export class SseTicketService {
    private http = inject(HttpClient);
    private authService = inject(AuthService);
    private configService = inject(ConfigService);

    private get ticketUrl(): string {
        return `${this.configService.apiUrl}auth/sse-ticket/`;
    }

    fetchTicket(): Observable<string> {
        const accessToken = this.authService.getAccessToken();
        if (!accessToken) return throwError(() => new Error('No access token available'));

        return this.requestTicket(accessToken).pipe(
            catchError((err) => {
                if (err?.status === 401) {
                    return this.authService.refreshToken().pipe(
                        switchMap((newToken) => {
                            if (!newToken) return throwError(() => new Error('Token refresh failed'));
                            return this.requestTicket(newToken);
                        })
                    );
                }
                return throwError(() => err);
            })
        );
    }

    private requestTicket(accessToken: string): Observable<string> {
        return this.http
            .post<SseTicketResponse>(this.ticketUrl, {}, { headers: { Authorization: `Bearer ${accessToken}` } })
            .pipe(switchMap(({ ticket }) => [ticket]));
    }
}
