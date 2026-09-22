import { UserRole } from '@shared/models';

export const ROLE_LABELS: Record<UserRole, string> = {
    [UserRole.SUPER_ADMIN]: 'Super Admin',
    [UserRole.ORG_ADMIN]: 'Organization Admin',
    [UserRole.MEMBER]: 'Member',
    [UserRole.VIEWER]: 'Viewer',
};
