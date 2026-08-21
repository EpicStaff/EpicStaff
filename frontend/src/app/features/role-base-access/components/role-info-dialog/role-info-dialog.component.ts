import { Dialog, DIALOG_DATA, DialogRef } from '@angular/cdk/dialog';
import { ChangeDetectionStrategy, Component, computed, DestroyRef, inject, OnInit } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { AppSvgIconComponent, ButtonComponent } from '@shared/components';
import { ActionCode, CatalogResponse, GetRoleResponse, ResourceCode } from '@shared/models';
import { rolePermissionsToSet } from '@shared/utils';

import { PermissionsService } from '../../../../services/auth/permissions.service';
import {
    CreateRoleDialogComponent,
    CreateRoleDialogData,
    CreateRoleDialogResult,
    DuplicateRoleSource,
} from '../create-role-dialog/create-role-dialog.component';
import { PermissionsTableComponent } from '../permissions-table/permissions-table.component';
import { UserAvatarComponent } from '../user-avatar/user-avatar.component';

@Component({
    selector: 'app-role-info-dialog',
    templateUrl: './role-info-dialog.component.html',
    styleUrls: ['./role-info-dialog.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
    imports: [AppSvgIconComponent, ButtonComponent, PermissionsTableComponent, UserAvatarComponent],
})
export class RoleInfoDialogComponent implements OnInit {
    private dialogRef = inject(DialogRef);
    private dialog = inject(Dialog);
    private destroyRef = inject(DestroyRef);
    private permissionsService = inject(PermissionsService);

    readonly role = inject<GetRoleResponse>(DIALOG_DATA);
    readonly catalog = computed<CatalogResponse | null>(() => this.permissionsService.catalog());

    readonly selectedPermissions = computed<Set<string>>(() => {
        const catalog = this.permissionsService.catalog();
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

    ngOnInit() {
        this.permissionsService.loadCatalog().pipe(takeUntilDestroyed(this.destroyRef)).subscribe();
    }

    /** Actor may duplicate this role if they can create roles in at least one org. */
    canDuplicate(): boolean {
        if (this.permissionsService.isSuperadmin) return true;
        return this.permissionsService.orgsWith(ResourceCode.Roles, ActionCode.Create).length > 0;
    }

    /** Closes the read-only view and opens create-role-dialog seeded from this role's state. */
    onDuplicate(): void {
        if (!this.canDuplicate()) return;
        const source: DuplicateRoleSource = {
            name: this.role.name,
            description: this.role.description,
            permissions: Array.from(this.selectedPermissions()),
            orgId: this.role.org_id,
        };
        this.dialogRef.close();
        this.dialog.open<CreateRoleDialogResult, CreateRoleDialogData>(CreateRoleDialogComponent, {
            width: 'calc(100vw - 2rem)',
            height: 'calc(100vh - 2rem)',
            disableClose: true,
            data: { duplicateSource: source },
        });
    }

    onClose(): void {
        this.dialogRef.close();
    }
}
