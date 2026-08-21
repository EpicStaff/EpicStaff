import { HttpClient, HttpHeaders } from '@angular/common/http';
import { inject, Injectable } from '@angular/core';
import { AdminCreateUserRequest, AdminCreateUserResponse } from '@shared/models';
import { Observable } from 'rxjs';

import { ApiGetRequest } from '../../../../core/models/api-request.model';
import { ConfigService } from '../../../../services/config';

@Injectable({
    providedIn: 'root',
})
export class AdminUserService {
    private readonly configService = inject(ConfigService);
    private readonly http = inject(HttpClient);

    private readonly httpHeaders = new HttpHeaders({
        'Content-Type': 'application/json',
    });

    private get apiUrl(): string {
        return this.configService.apiUrl + 'admin/users/';
    }

    createUser(dto: AdminCreateUserRequest): Observable<AdminCreateUserResponse> {
        return this.http.post<AdminCreateUserResponse>(this.apiUrl, dto, {
            headers: this.httpHeaders,
        });
    }

    getUsers(): Observable<ApiGetRequest<AdminCreateUserResponse>> {
        return this.http.get<ApiGetRequest<AdminCreateUserResponse>>(this.apiUrl);
    }

    grantSuperadmin(userId: number): Observable<void> {
        return this.http.post<void>(
            `${this.apiUrl}${userId}/grant-superadmin/`,
            {},
            {
                headers: this.httpHeaders,
            }
        );
    }

    revokeSuperadmin(userId: number): Observable<void> {
        return this.http.post<void>(
            `${this.apiUrl}${userId}/revoke-superadmin/`,
            {},
            {
                headers: this.httpHeaders,
            }
        );
    }

    deactivateUser(userId: number): Observable<void> {
        return this.http.post<void>(`${this.apiUrl}${userId}/deactivate/`, {}, { headers: this.httpHeaders });
    }

    reactivateUser(userId: number): Observable<void> {
        return this.http.post<void>(`${this.apiUrl}${userId}/reactivate/`, {}, { headers: this.httpHeaders });
    }

    resetPassword(userId: number): Observable<void> {
        return this.http.post<void>(`${this.apiUrl}${userId}/reset-password/`, {}, { headers: this.httpHeaders });
    }
}
