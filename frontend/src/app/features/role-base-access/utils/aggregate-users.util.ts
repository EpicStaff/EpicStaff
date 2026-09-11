import { AdminCreateUserResponse, AdminMembershipRow, FullMembership } from '@shared/models';

import { AggregatedUser } from '../models/aggregated-user.model';

/** Superadmin path: `/api/admin/users/` already returns one account per row with
 *  its full `memberships` array — just remap snake_case to the UI shape. */
export function adminUsersToAggregated(users: AdminCreateUserResponse[]): AggregatedUser[] {
    return users.map((u) => ({
        id: u.id,
        email: u.email,
        displayName: u.display_name,
        avatarUrl: u.avatar_url,
        isSuperadmin: u.is_superadmin,
        isActive: u.is_active,
        memberships: u.memberships,
    }));
}

/** Delegated-admin path: `/api/admin/memberships/` returns one row per user-in-org,
 *  so multiple rows can share a user. Group by user id; first row wins on user fields. */
export function aggregateMembershipsByUser(rows: AdminMembershipRow[]): AggregatedUser[] {
    const byUser = new Map<number, AggregatedUser>();
    for (const row of rows) {
        const membership: FullMembership = {
            id: row.id,
            organization: row.org,
            role: row.role,
            joined_at: row.joined_at,
        };
        const existing = byUser.get(row.user.id);
        if (existing) {
            existing.memberships.push(membership);
        } else {
            byUser.set(row.user.id, {
                id: row.user.id,
                email: row.user.email,
                displayName: row.user.display_name,
                avatarUrl: row.user.avatar_url,
                isSuperadmin: row.user.is_superadmin,
                isActive: row.user.is_active,
                memberships: [membership],
            });
        }
    }
    return Array.from(byUser.values());
}
