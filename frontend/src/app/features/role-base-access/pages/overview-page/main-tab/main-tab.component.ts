import { Dialog } from '@angular/cdk/dialog';
import { ChangeDetectionStrategy, Component, computed, DestroyRef, inject, OnInit, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { AppSvgIconComponent, ButtonComponent, LoadingSpinnerComponent } from '@shared/components';
import { finalize } from 'rxjs';

import { ToastService } from '../../../../../services/notifications';
import { CreateOrganizationDialogComponent } from '../../../components/create-organization-dialog/create-organization-dialog.component';
import { OrgCardComponent } from '../../../components/org-card/org-card.component';
import { StatCardComponent } from '../../../components/stat-card/stat-card.component';
import { StatCardData } from '../../../components/stat-card/stat-card.interface';
import { AdminUserService } from '../../../services/admin/admin-user.service';
import { OrganizationsStorageService } from '../../../services/admin/organizations-storage.service';
import { RolesService } from '../../../services/admin/roles.service';

@Component({
    selector: 'app-workspace-main',
    imports: [StatCardComponent, ButtonComponent, OrgCardComponent, AppSvgIconComponent, LoadingSpinnerComponent],
    templateUrl: './main-tab.component.html',
    styleUrls: ['./main-tab.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class MainTabComponent implements OnInit {
    private dialog = inject(Dialog);
    private destroyRef = inject(DestroyRef);
    private organizationStorage = inject(OrganizationsStorageService);
    private adminUserService = inject(AdminUserService);
    private rolesService = inject(RolesService);
    private toast = inject(ToastService);

    organizations = this.organizationStorage.organizations;
    isOrgsLoading = signal(true);
    isUsersLoading = signal(true);
    isRolesLoading = signal(true);
    usersCount = signal(0);

    stats = computed<StatCardData[]>(() => [
        {
            label: 'TOTAL ORGANIZATIONS',
            icon: 'buildings',
            value: this.organizations().length,
            loading: this.isOrgsLoading(),
        },
        {
            label: 'TOTAL USERS',
            icon: 'profile',
            value: this.usersCount(),
            loading: this.isUsersLoading(),
        },
        {
            label: 'ROLES',
            icon: 'briefcase',
            value: this.rolesService.roles().length,
            loading: this.isRolesLoading(),
        },
    ]);

    ngOnInit(): void {
        this.getOrganizations();
        this.getUsers();
        this.getRoles();
    }

    private getOrganizations(): void {
        this.organizationStorage
            .getOrganizations(true)
            .pipe(
                takeUntilDestroyed(this.destroyRef),
                finalize(() => this.isOrgsLoading.set(false))
            )
            .subscribe();
    }

    private getUsers(): void {
        this.adminUserService
            .getUsers()
            .pipe(
                takeUntilDestroyed(this.destroyRef),
                finalize(() => this.isUsersLoading.set(false))
            )
            .subscribe({
                next: ({ count }) => this.usersCount.set(count),
                error: () => this.toast.error('Failed to fetch users count.'),
            });
    }

    private getRoles(): void {
        this.rolesService
            .loadRoles()
            .pipe(
                takeUntilDestroyed(this.destroyRef),
                finalize(() => this.isRolesLoading.set(false))
            )
            .subscribe();
    }

    onCreateOrganization(): void {
        this.dialog.open(CreateOrganizationDialogComponent, {
            width: 'calc(100vw - 2rem)',
            height: 'calc(100vh - 2rem)',
            disableClose: true,
        });
    }
}
