import { HttpClient } from '@angular/common/http';
import { inject, Injectable, signal } from '@angular/core';
import { GetRoleResponse } from '@shared/models';
import { StorageService } from '@shared/services';
import { Observable, of, tap } from 'rxjs';

import { ConfigService } from '../../../../services/config';

@Injectable({
    providedIn: 'root',
})
export class RolesService implements StorageService {
    private readonly configService = inject(ConfigService);
    private readonly http = inject(HttpClient);

    private get apiUrl(): string {
        return this.configService.apiUrl + 'admin/roles/';
    }

    private readonly _roles = signal<GetRoleResponse[]>([]);
    readonly roles = this._roles.asReadonly();

    private _loaded = false;

    loadRoles(): Observable<GetRoleResponse[]> {
        if (this._loaded) return of(this._roles());
        return this.http.get<GetRoleResponse[]>(this.apiUrl).pipe(
            tap((roles) => {
                this._roles.set(roles);
                this._loaded = true;
            })
        );
    }

    getRoleById(id: number): Observable<GetRoleResponse> {
        return this.http.get<GetRoleResponse>(`${this.apiUrl}${id}/`);
    }

    deleteRole(roleId: number): Observable<void> {
        return this.http
            .delete<void>(`${this.apiUrl}${roleId}/`)
            .pipe(tap(() => this._roles.update((roles) => roles.filter((r) => r.id !== roleId))));
    }

    clear(): void {
        this._roles.set([]);
        this._loaded = false;
    }
}
