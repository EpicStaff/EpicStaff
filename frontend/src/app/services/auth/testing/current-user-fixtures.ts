import { HttpTestingController } from '@angular/common/http/testing';
import {
    ActivePermissions,
    GetMeResponse,
    MyOrgPermissionsResponse,
    Organization,
    OrgCapability,
} from '@shared/models';

/** The `apiUrl` the specs give `ConfigService`. */
export const API_URL = '/api/';
export const PROFILE_URL = '/api/profile/';
export const ACTIVE_PERMISSIONS_URL = '/api/permissions/me/';
export const ORG_PERMISSIONS_URL = '/api/permissions/me/orgs/';

export const ORGANIZATION_A: Organization = { id: 1, name: 'A' };
export const ORGANIZATION_B: Organization = { id: 2, name: 'B' };

/** The signed-in user's profile, a member of `organizations` in that order. */
export function memberOf(...organizations: Organization[]): GetMeResponse {
    return {
        id: 7,
        email: 'jane@example.com',
        display_name: 'Jane Doe',
        is_superadmin: false,
        is_active: true,
        created_at: '2026-01-01T00:00:00Z',
        updated_at: '2026-01-01T00:00:00Z',
        memberships: organizations.map((organization, index) => ({
            id: 100 + index,
            organization,
            role: { id: 3, name: 'Member' },
            joined_at: '2026-01-01T00:00:00Z',
        })),
        active_organization_id: organizations[0]?.id ?? null,
        active_permissions: null,
        avatar_url: null,
        completed_tours: [],
        custom_shortcuts: { custom: [], overrides: {} },
    };
}

/** What `GET /permissions/me/` answers in the org the request names. */
function permissionsIn(orgId: number, isSuperadmin = false): ActivePermissions {
    return { org_id: orgId, is_superadmin: isSuperadmin, role: { id: 3, name: 'Member' }, permissions: '*' };
}

function orgPermissionsOf(user: GetMeResponse): MyOrgPermissionsResponse {
    return {
        is_superadmin: user.is_superadmin,
        orgs: user.memberships.map(
            ({ organization, role }): OrgCapability => ({
                org: organization,
                role,
                permissions: {} as OrgCapability['permissions'],
            })
        ),
    };
}

/**
 * Plays the backend for a load of the signed-in user: answers the profile with `user`, then the cross-org
 * permissions and the permissions in whichever org the request's `X-Organization-Id` names.
 */
export function answerUserLoad(http: HttpTestingController, user: GetMeResponse): void {
    http.expectOne({ method: 'GET', url: PROFILE_URL }).flush(user);
    answerPermissionsLoad(http, user);
}

/** Answers the permission requests a load of `user` makes after the profile arrived. */
function answerPermissionsLoad(http: HttpTestingController, user: GetMeResponse): void {
    http.expectOne({ method: 'GET', url: ORG_PERMISSIONS_URL }).flush(orgPermissionsOf(user));
    if (user.memberships.length === 0) return;
    const request = http.expectOne({ method: 'GET', url: ACTIVE_PERMISSIONS_URL });
    request.flush(permissionsIn(Number(request.request.headers.get('X-Organization-Id')), user.is_superadmin));
}
