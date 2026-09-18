import { FullMembership } from '@shared/models';

/** UI-shape used by the Users tab and the create/edit user dialog. */
export interface AggregatedUser {
    id: number;
    email: string;
    displayName: string | null;
    avatarUrl: string | null;
    isSuperadmin: boolean;
    isActive: boolean;
    memberships: FullMembership[];
}
