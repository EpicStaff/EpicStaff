import { DIALOG_DATA, DialogRef } from '@angular/cdk/dialog';
import { ChangeDetectionStrategy, Component, computed, inject } from '@angular/core';
import { AppSvgIconComponent } from '@shared/components';
import { CatalogResponse, GetRoleResponse } from '@shared/models';
import { rolePermissionsToSet } from '@shared/utils';

import { PermissionsService } from '../../../../services/auth/permissions.service';
import { PermissionsTableComponent } from '../permissions-table/permissions-table.component';
import { UserAvatarComponent } from '../user-avatar/user-avatar.component';

@Component({
    selector: 'app-role-info-dialog',
    templateUrl: './role-info-dialog.component.html',
    styleUrls: ['./role-info-dialog.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
    imports: [AppSvgIconComponent, PermissionsTableComponent, UserAvatarComponent],
})
export class RoleInfoDialogComponent {
    private dialogRef = inject(DialogRef);
    private rolesCatalogService = inject(PermissionsService);

    readonly role = inject<GetRoleResponse>(DIALOG_DATA);
    readonly catalog = computed<CatalogResponse | null>(() => this.rolesCatalogService.catalog());

    readonly selectedPermissions = computed<Set<string>>(() => {
        const catalog = this.rolesCatalogService.catalog();
        if (catalog && this.role.is_built_in && this.role.name === 'Superadmin') {
            const all = new Set<string>();
            for (const rt of catalog.resource_types) {
                for (const action of rt.applicable_actions) {
                    all.add(`${rt.code}:${action}`);
                }
            }
            return all;
        }
        return rolePermissionsToSet(this.role.permissions);
    });

    onClose(): void {
        this.dialogRef.close();
    }
}
