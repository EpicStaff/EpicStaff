import { DIALOG_DATA, DialogRef } from '@angular/cdk/dialog';
import { Component, computed, DestroyRef, inject, OnInit, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { MatTooltipModule } from '@angular/material/tooltip';
import { AppSvgIconComponent, LoadingSpinnerComponent, UserAvatarComponent } from '@shared/components';
import { TooltipOnOverflowDirective } from '@shared/directives';
import { CatalogAction, MyOrgPermissionsResponse, Organization } from '@shared/models';
import { forkJoin, Observable, of } from 'rxjs';

import { PermissionsService } from '../../../../services/auth/permissions.service';
import { ACTION_ICONS } from '../../constants/permission-table.constant';
import { buildGrantedPermissionGroups, GrantedPermissionGroup, RoleGrants } from '../../utils';

/** One membership of the current user: the role it holds in that organization. */
export interface RolePermissionsDialogData {
    organization: Organization;
    roleId: number;
    roleName: string;
    /** A platform superadmin holds every applicable permission, whatever the membership role says. */
    isSuperadmin: boolean;
}

/** Pass as `ariaLabelledBy` when opening the dialog; only one instance is open at a time. */
export const ROLE_PERMISSIONS_DIALOG_TITLE_ID = 'role-permissions-dialog-title';

type RolePermissionsStatus = 'loading' | 'failed' | 'not-found' | 'ready';

/** Read-only list of the permissions the current user's role grants in one organization. */
@Component({
    selector: 'app-role-permissions-dialog',
    templateUrl: './role-permissions-dialog.component.html',
    styleUrls: ['./role-permissions-dialog.component.scss'],
    imports: [
        AppSvgIconComponent,
        LoadingSpinnerComponent,
        UserAvatarComponent,
        MatTooltipModule,
        TooltipOnOverflowDirective,
    ],
})
export class RolePermissionsDialogComponent implements OnInit {
    private readonly hasLoadFailed = signal(false);
    /** Whether `/me/orgs/` was re-fetched for this dialog, so a missing role is really missing, not stale. */
    private readonly hasFreshOrgPermissions = signal(false);
    protected readonly collapsedGroups = signal<ReadonlySet<string>>(new Set());

    /** Cached permissions render right away; the refresh replaces them when it lands. */
    protected readonly status = computed<RolePermissionsStatus>(() => {
        // A failed refresh wins over cached grants: stale permissions must not be shown as current.
        if (this.hasLoadFailed()) return 'failed';
        if (!this.permissionsService.catalog()) return 'loading';
        if (this.roleGrants()) return 'ready';
        return this.hasFreshOrgPermissions() ? 'not-found' : 'loading';
    });

    protected readonly groups = computed<GrantedPermissionGroup[]>(() => {
        const catalog = this.permissionsService.catalog();
        const grants = this.roleGrants();
        if (!catalog || !grants) return [];
        return buildGrantedPermissionGroups(catalog, grants);
    });

    private readonly roleGrants = computed<RoleGrants | null>(() => {
        if (this.data.isSuperadmin) return '*';
        const orgCapabilities = this.permissionsService.orgCaps()?.orgs ?? [];
        const membership = orgCapabilities.find((orgCapability) => orgCapability.org.id === this.data.organization.id);
        // A different role in that org means the profile is out of date: this role is no longer held there.
        if (membership?.role?.id !== this.data.roleId) return null;
        return membership.permissions;
    });

    protected readonly data = inject<RolePermissionsDialogData>(DIALOG_DATA);
    protected readonly titleId = ROLE_PERMISSIONS_DIALOG_TITLE_ID;

    private readonly dialogRef = inject(DialogRef);
    private readonly destroyRef = inject(DestroyRef);
    private readonly permissionsService = inject(PermissionsService);

    ngOnInit(): void {
        forkJoin([this.permissionsService.loadCatalog(), this.refreshOrgPermissions()])
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe({
                next: () => this.hasFreshOrgPermissions.set(true),
                error: () => this.hasLoadFailed.set(true),
            });
    }

    protected isGroupCollapsed(groupKey: string): boolean {
        return this.collapsedGroups().has(groupKey);
    }

    protected toggleGroup(groupKey: string): void {
        this.collapsedGroups.update((collapsed) => {
            const next = new Set(collapsed);
            if (next.has(groupKey)) {
                next.delete(groupKey);
            } else {
                next.add(groupKey);
            }
            return next;
        });
    }

    protected actionLabel(action: CatalogAction): string {
        return action.label || action.code.charAt(0).toUpperCase() + action.code.slice(1);
    }

    protected actionIcon(action: CatalogAction): string {
        return ACTION_ICONS[action.code] ?? 'circle';
    }

    protected permissionCountLabel(count: number): string {
        return `${count} ${count === 1 ? 'permission' : 'permissions'}`;
    }

    protected onClose(): void {
        this.dialogRef.close();
    }

    /** Memberships change without `/me/orgs/` being reloaded, so the cached copy may be stale.
     *  The superadmin view needs only the catalog. */
    private refreshOrgPermissions(): Observable<MyOrgPermissionsResponse | null> {
        if (this.data.isSuperadmin) return of(null);
        return this.permissionsService.loadOrgPermissions();
    }
}
