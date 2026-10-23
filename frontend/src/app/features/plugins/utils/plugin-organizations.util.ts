import { GetOrganizationResponse } from '@shared/models';
import { EMPTY, expand, map, Observable, reduce } from 'rxjs';

import {
    AdminOrganizationsService,
    ListOrganizationsParams,
} from '../../role-base-access/services/admin/organizations.service';

/** The most organizations one admin list request returns. */
const ORGANIZATIONS_PAGE_SIZE = 200;

/** Every organization the SuperAdmin's list has (only active or inactive ones when asked), sorted by name. */
export function fetchAllOrganizations(
    organizations: AdminOrganizationsService,
    filter: Pick<ListOrganizationsParams, 'is_active'> = {}
): Observable<GetOrganizationResponse[]> {
    const fetchPage = (page: number) =>
        organizations
            .list({ ...filter, page, page_size: ORGANIZATIONS_PAGE_SIZE })
            .pipe(map((response) => ({ response, page })));
    return fetchPage(1).pipe(
        expand(({ response, page }) => (response.next && response.results.length > 0 ? fetchPage(page + 1) : EMPTY)),
        reduce((all: GetOrganizationResponse[], { response }) => all.concat(response.results), []),
        map((all) => [...all].sort((first, second) => first.name.localeCompare(second.name)))
    );
}
