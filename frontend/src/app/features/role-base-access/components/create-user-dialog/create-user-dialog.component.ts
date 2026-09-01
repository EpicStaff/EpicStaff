import { DIALOG_DATA, DialogRef } from '@angular/cdk/dialog';
import { HttpErrorResponse } from '@angular/common/http';
import {
    ChangeDetectionStrategy,
    Component,
    computed,
    DestroyRef,
    inject,
    OnInit,
    signal,
    viewChild,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { ButtonComponent, ConfirmationDialogService, LoadingSpinnerComponent } from '@shared/components';
import { FullMembership, Organization } from '@shared/models';
import { catchError, concat, forkJoin, map, Observable, of, switchMap, toArray } from 'rxjs';
import { finalize } from 'rxjs/operators';

import { ToastService } from '../../../../services/notifications';
import { AggregatedUser } from '../../models/aggregated-user.model';
import { AdminUserService } from '../../services/admin/admin-user.service';
import { MembershipsService } from '../../services/admin/memberships.service';
import { OrganizationsStorageService } from '../../services/admin/organizations-storage.service';
import { rbacErrorMessage } from '../../utils/rbac-error-messages.util';
import { OrgAssignment, StepAssignToOrgComponent } from './steps/assign-to-org/step-assign-to-org.component';
import { StepUserDetailsComponent } from './steps/user-details/step-user-details.component';

export interface UserDialogData {
    user?: AggregatedUser;
}

@Component({
    selector: 'app-create-user-dialog',
    templateUrl: './create-user-dialog.component.html',
    styleUrls: ['./create-user-dialog.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
    imports: [ButtonComponent, StepUserDetailsComponent, StepAssignToOrgComponent, LoadingSpinnerComponent],
})
export class CreateUserDialogComponent implements OnInit {
    private destroyRef = inject(DestroyRef);
    private dialogRef = inject(DialogRef);
    private dialogData = inject<UserDialogData>(DIALOG_DATA, { optional: true });
    private adminUserService = inject(AdminUserService);
    private membershipsService = inject(MembershipsService);
    private organizationsStorage = inject(OrganizationsStorageService);
    private toast = inject(ToastService);
    private confirmation = inject(ConfirmationDialogService);

    private userDetailsStep = viewChild(StepUserDetailsComponent);
    private assignToOrgStep = viewChild(StepAssignToOrgComponent);

    editUser = signal<AggregatedUser | null>(this.dialogData?.user ?? null);
    availableOrganizations = signal<Organization[]>([]);
    isSubmitting = signal<boolean>(false);
    loadingOrganizations = signal<boolean>(true);

    editMode = computed(() => this.editUser() !== null);
    existingMemberships = computed<FullMembership[]>(() => this.editUser()?.memberships ?? []);
    submitDisabled = computed(() => !(this.userDetailsStep()?.isFormValid() ?? false) || this.isSubmitting());

    ngOnInit(): void {
        this.loadOrganizations();
    }

    onClose(): void {
        this.dialogRef.close();
    }

    onSubmit(): void {
        const detailsStep = this.userDetailsStep();
        if (!detailsStep || !detailsStep.isFormValid()) return;

        this.isSubmitting.set(true);

        const { email, password, superadmin } = detailsStep.form.getRawValue();
        const assignments = this.assignToOrgStep()?.getAssignments() ?? [];

        this.performSubmit(email!, password!, superadmin ?? false, assignments)
            .pipe(
                takeUntilDestroyed(this.destroyRef),
                finalize(() => this.isSubmitting.set(false))
            )
            .subscribe({
                next: (success) => {
                    if (!success) return;
                    this.toast.success(this.editMode() ? 'User updated successfully.' : 'User created successfully.');
                    this.dialogRef.close(true);
                },
                error: (err: HttpErrorResponse) => this.toast.error(rbacErrorMessage(err, 'Operation failed.')),
            });
    }

    private performSubmit(
        email: string,
        password: string,
        superadmin: boolean,
        assignments: OrgAssignment[]
    ): Observable<boolean> {
        if (this.editMode()) {
            const user = this.editUser()!;
            const grantingSuperadmin = superadmin && !user.isSuperadmin && user.memberships.length > 0;
            if (grantingSuperadmin) {
                return this.confirmGrantSuperadmin(user).pipe(
                    switchMap((confirmed) =>
                        confirmed ? this.updateExistingUser(user, assignments, superadmin) : of(false)
                    )
                );
            }
            return this.updateExistingUser(user, assignments, superadmin);
        }
        return this.createUserAsSuperadmin(email, password, superadmin, assignments);
    }

    private confirmGrantSuperadmin(user: AggregatedUser): Observable<boolean> {
        const label = user.displayName || user.email;
        const rolesList = user.memberships
            .map((m) => `<strong>${m.role.name}</strong> in <strong>${m.organization.name}</strong>`)
            .join(', ');
        return this.confirmation
            .confirm({
                title: `Make ${label} a superadmin?`,
                message: `${label} will lose ${rolesList}. Revoking superadmin later will not restore them. Superadmins reach every organization already.`,
                confirmText: 'Grant superadmin',
                cancelText: 'Cancel',
                type: 'danger',
            })
            .pipe(map((result) => result === true));
    }

    private createUserAsSuperadmin(
        email: string,
        password: string,
        superadmin: boolean,
        assignments: OrgAssignment[]
    ): Observable<boolean> {
        return this.adminUserService.createUser({ email, password }).pipe(
            switchMap((user) =>
                (superadmin ? this.adminUserService.grantSuperadmin(user.id) : of(void 0)).pipe(map(() => user.id))
            ),
            switchMap((userId) => this.createMembershipsForUser(userId, assignments)),
            map(() => true)
        );
    }

    private createMembershipsForUser(userId: number, assignments: OrgAssignment[]): Observable<unknown> {
        if (!assignments.length) return of(null);
        const ops = assignments.map((a) =>
            this.membershipsService.create({ org_id: a.orgId, user_id: userId, role_id: a.roleId })
        );
        return concat(...ops).pipe(toArray());
    }

    /** Edit flow: diff `assignments` vs existing memberships and superadmin flag.
     *   - Role change on existing membership → PATCH.
     *   - New org → POST.
     *   - Removed org → DELETE.
     *   - Superadmin toggle → grant/revoke. */
    private updateExistingUser(
        user: AggregatedUser,
        assignments: OrgAssignment[],
        wantsSuperadmin: boolean
    ): Observable<boolean> {
        const membershipByOrg = new Map(user.memberships.map((m) => [m.organization.id, m]));
        const wantedByOrg = new Map(assignments.map((a) => [a.orgId, a.roleId]));

        const ops: Observable<unknown>[] = [];

        // Superadmin diff first (grant/revoke can affect visibility of subsequent ops).
        if (wantsSuperadmin !== user.isSuperadmin) {
            ops.push(
                wantsSuperadmin
                    ? this.adminUserService.grantSuperadmin(user.id)
                    : this.adminUserService.revokeSuperadmin(user.id)
            );
        }

        // Adds & role updates.
        for (const a of assignments) {
            const existing = membershipByOrg.get(a.orgId);
            if (!existing) {
                ops.push(this.membershipsService.create({ org_id: a.orgId, user_id: user.id, role_id: a.roleId }));
            } else if (existing.role.id !== a.roleId) {
                ops.push(this.membershipsService.updateRole(existing.id, { role_id: a.roleId }));
            }
        }

        // Removals.
        for (const m of user.memberships) {
            if (!wantedByOrg.has(m.organization.id)) {
                ops.push(this.membershipsService.remove(m.id));
            }
        }

        if (!ops.length) return of(true);
        return forkJoin(ops).pipe(map(() => true));
    }

    private loadOrganizations(): void {
        this.organizationsStorage
            .getOrganizations()
            .pipe(
                takeUntilDestroyed(this.destroyRef),
                finalize(() => this.loadingOrganizations.set(false)),
                catchError(() => of([] as Organization[]))
            )
            .subscribe((orgs) => this.availableOrganizations.set(orgs));
    }
}
