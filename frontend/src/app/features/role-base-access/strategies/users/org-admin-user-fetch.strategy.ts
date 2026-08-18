import { ActionCode, FullMembership, OrgUserResponse, ResourceCode } from '@shared/models';
import { forkJoin, map, Observable, of } from 'rxjs';

import { PermissionsService } from '../../../../services/auth/permissions.service';
import { UserService } from '../../services/users/user.service';
import { NormalizedUser, UserFetchStrategy } from './user-fetch.strategy';

export class OrgAdminUserFetchStrategy implements UserFetchStrategy {
    constructor(
        private userService: UserService,
        private permissionsService: PermissionsService
    ) {}

    fetchUsers(): Observable<NormalizedUser[]> {
        const readableOrgs = this.permissionsService.orgsWith(ResourceCode.Users, ActionCode.Read);
        if (!readableOrgs.length) return of([]);

        // Build orgId → org lookup (per-org endpoint doesn't return org info).
        const orgById = new Map(readableOrgs.map((org) => [org.id, org]));

        const requests = readableOrgs.map((org) =>
            this.userService.getUsers(org.id).pipe(map((users) => ({ orgId: org.id, users })))
        );

        return forkJoin(requests).pipe(map((results) => this.mergeAndDeduplicate(results, orgById)));
    }

    private mergeAndDeduplicate(
        orgResults: { orgId: number; users: OrgUserResponse[] }[],
        orgById: Map<number, { id: number; name: string }>
    ): NormalizedUser[] {
        const userMap = new Map<number, NormalizedUser>();

        for (const { orgId, users } of orgResults) {
            const organization = orgById.get(orgId) ?? { id: orgId, name: '' };

            for (const user of users) {
                const membership: FullMembership = {
                    organization,
                    id: user.membership.id,
                    role: user.membership.role,
                    joined_at: user.membership.joined_at,
                };

                const existing = userMap.get(user.id);
                if (existing) {
                    if (!existing.memberships.some((m) => m.organization.id === orgId)) {
                        existing.memberships.push(membership);
                    }
                } else {
                    userMap.set(user.id, {
                        id: user.id,
                        email: user.email,
                        avatarUrl: user.avatar_url,
                        displayName: user.display_name,
                        isSuperadmin: user.is_superadmin,
                        isActive: user.is_active,
                        memberships: [membership],
                    });
                }
            }
        }

        return Array.from(userMap.values());
    }
}
