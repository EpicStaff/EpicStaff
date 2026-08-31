import { HttpClient, HttpParams } from '@angular/common/http';
import { inject, Injectable } from '@angular/core';
import {
    ActionCode,
    AdminMembershipRow,
    CreateMembershipRequest,
    ListMembershipsParams,
    ResourceCode,
    UpdateMembershipRequest,
} from '@shared/models';
import { Observable } from 'rxjs';

import { withCrossOrgPermission } from '../../../../core/http/permission-context';
import { ApiGetRequest } from '../../../../core/models/api-request.model';
import { ConfigService } from '../../../../services/config';

@Injectable({
    providedIn: 'root',
})
export class MembershipsService {
    private readonly configService = inject(ConfigService);
    private readonly http = inject(HttpClient);

    private get apiUrl(): string {
        return this.configService.apiUrl + 'admin/memberships/';
    }

    /** GET /api/admin/memberships/?org_ids=…&search=…&role_id=…&status=…&ordering=…&page=… */
    list(params: ListMembershipsParams = {}): Observable<ApiGetRequest<AdminMembershipRow>> {
        let httpParams = new HttpParams();
        if (params.org_ids?.length) httpParams = httpParams.set('org_ids', params.org_ids.join(','));
        if (params.role_id !== undefined) httpParams = httpParams.set('role_id', String(params.role_id));
        if (params.status) httpParams = httpParams.set('status', params.status);
        if (params.search) httpParams = httpParams.set('search', params.search);
        if (params.ordering) httpParams = httpParams.set('ordering', params.ordering);
        if (params.page !== undefined) httpParams = httpParams.set('page', String(params.page));
        if (params.page_size !== undefined) httpParams = httpParams.set('page_size', String(params.page_size));
        return this.http.get<ApiGetRequest<AdminMembershipRow>>(this.apiUrl, {
            params: httpParams,
            context: withCrossOrgPermission<ApiGetRequest<AdminMembershipRow>>(
                ResourceCode.Memberships,
                ActionCode.Read,
                {
                    count: 0,
                    next: null,
                    previous: null,
                    results: [],
                }
            ),
        });
    }

    /** POST /api/admin/memberships/ — link an existing account to an org. */
    create(dto: CreateMembershipRequest): Observable<AdminMembershipRow> {
        return this.http.post<AdminMembershipRow>(this.apiUrl, dto);
    }

    /** PATCH /api/admin/memberships/{id}/ — change role on an existing membership. */
    updateRole(membershipId: number, dto: UpdateMembershipRequest): Observable<AdminMembershipRow> {
        return this.http.patch<AdminMembershipRow>(`${this.apiUrl}${membershipId}/`, dto);
    }

    /** DELETE /api/admin/memberships/{id}/ — remove a user from an org. */
    remove(membershipId: number): Observable<void> {
        return this.http.delete<void>(`${this.apiUrl}${membershipId}/`);
    }
}
