import { PermissionsService } from '../../../../services/auth/permissions.service';
import { ProfileService } from '../../../../services/auth/profile.service';
import { AdminUserService } from '../../services/admin/admin-user.service';
import { UserService } from '../../services/users/user.service';
import { OrgAdminUserFetchStrategy } from './org-admin-user-fetch.strategy';
import { SuperAdminUserFetchStrategy } from './super-admin-user-fetch.strategy';
import { UserFetchStrategy } from './user-fetch.strategy';

export function createUserFetchStrategy(
    currentUserService: ProfileService,
    adminUserService: AdminUserService,
    userService: UserService,
    permissionsService: PermissionsService
): UserFetchStrategy {
    const isSuperAdmin = currentUserService.isMeSuperAdmin();

    if (isSuperAdmin) {
        return new SuperAdminUserFetchStrategy(adminUserService);
    }

    return new OrgAdminUserFetchStrategy(userService, permissionsService);
}
