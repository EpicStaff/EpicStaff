import { Dialog, DIALOG_DATA, DialogRef } from '@angular/cdk/dialog';
import { ChangeDetectionStrategy, Component, computed, DestroyRef, inject, OnInit } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { AppSvgIconComponent, ButtonComponent, UserAvatarComponent } from '@shared/components';
import { ActionCode, CatalogResponse, GetRoleResponse, ResourceCode } from '@shared/models';
import { rolePermissionsToSet } from '@shared/utils';

import { PermissionsService } from '../../../../services/auth/permissions.service';
import {
    CreateRoleDialogComponent,
    CreateRoleDialogData,
    CreateRoleDialogResult,
    DuplicateRoleSource,
} from '../create-role-dialog/create-role-dialog.component';
import { PermissionExtensionRowsService } from '../permissions-table/permission-extension-rows.service';
import { PermissionsTableComponent } from '../permissions-table/permissions-table.component';

@Component({
    selector: 'app-role-info-dialog',
    templateUrl: './role-info-dialog.component.html',
    styleUrls: ['./role-info-dialog.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
    imports: [AppSvgIconComponent, ButtonComponent, PermissionsTableComponent, UserAvatarComponent],
    providers: [PermissionExtensionRowsService],
})
export class RoleInfoDialogComponent implements OnInit {
    private dialogRef = inject(DialogRef);
    private dialog = inject(Dialog);
    private destroyRef = inject(DestroyRef);
    private permissionsService = inject(PermissionsService);
    /** Rows extensions (e.g. plugins) add; a built-in role shows the defaults each extension gives it. */
    protected readonly extensionRows = inject(PermissionExtensionRowsService);

    readonly role = inject<GetRoleResponse>(DIALOG_DATA);
    readonly catalog = computed<CatalogResponse | null>(() => this.permissionsService.catalog());

    /** The global built-in Superadmin role: shown with every catalog permission, while extensions show a note, since
     *  the role itself holds nothing (a superadmin's authority comes from the account). */
    private readonly isSuperadminRole = this.role.is_built_in && this.role.name === 'Superadmin';

    readonly selectedPermissions = computed<Set<string>>(() => {
        const catalog = this.permissionsService.catalog();
        if (catalog && this.isSuperadminRole) {
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

    /** What the table shows as ticked: catalog permissions and extension cells together. */
    readonly matrixSelection = computed<ReadonlySet<string>>(
        () => new Set([...this.selectedPermissions(), ...this.extensionRows.selected()])
    );

    /** Extension rows that could not be loaded. */
    readonly extensionNotice = computed<string | null>(() => {
        const failures = this.extensionRows.loadFailures();
        return failures.length > 0 ? failures.map((failure) => failure.message).join(' ') : null;
    });

    ngOnInit() {
        this.permissionsService.loadCatalog().pipe(takeUntilDestroyed(this.destroyRef)).subscribe();
        if (this.isSuperadminRole) {
            this.extensionRows.showSuperadminNotes();
            return;
        }
        // No organization: a built-in role then shows its rows in every organization the actor can read.
        this.extensionRows.loadForRole(this.role.id);
    }

    /** Actor may duplicate this role if they can create roles in at least one org. */
    canDuplicate(): boolean {
        if (this.permissionsService.isSuperadmin) return true;
        return this.permissionsService.orgsWith(ResourceCode.Roles, ActionCode.Create).length > 0;
    }

    /** Closes the read-only view and opens create-role-dialog seeded from this role's state. */
    onDuplicate(): void {
        // The copy carries the extension cells, so it waits for them.
        if (!this.canDuplicate() || this.extensionRows.isLoading()) return;
        const source: DuplicateRoleSource = {
            name: this.role.name,
            description: this.role.description,
            permissions: Array.from(this.selectedPermissions()),
            extensionPermissions: Array.from(this.extensionRows.selected()),
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
