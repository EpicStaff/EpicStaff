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
import { ButtonComponent, HelpTooltipComponent, SelectComponent, SelectItem } from '@shared/components';
import { AssignableUsersResponse, FullMembership, Organization } from '@shared/models';
import { forkJoin, map, Observable, of } from 'rxjs';
import { catchError, finalize } from 'rxjs/operators';

import { ProfileService } from '../../../../services/auth/profile.service';
import { ToastService } from '../../../../services/notifications';
import { AggregatedUser } from '../../models/aggregated-user.model';
import { MembershipsService } from '../../services/admin/memberships.service';
import { rbacErrorMessage } from '../../utils/rbac-error-messages.util';
import {
    OrgAssignment,
    StepAssignToOrgComponent,
} from '../create-user-dialog/steps/assign-to-org/step-assign-to-org.component';

export interface MembershipDialogData {
    user?: AggregatedUser;
}

@Component({
    selector: 'app-create-membership-dialog',
    templateUrl: './create-membership-dialog.component.html',
    styleUrls: ['./create-membership-dialog.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
    imports: [ButtonComponent, StepAssignToOrgComponent, HelpTooltipComponent, SelectComponent],
})
export class CreateMembershipDialogComponent implements OnInit {
    private destroyRef = inject(DestroyRef);
    private dialogRef = inject(DialogRef);
    private dialogData = inject<MembershipDialogData>(DIALOG_DATA, { optional: true });
    private profileService = inject(ProfileService);
    private membershipsService = inject(MembershipsService);
    private toast = inject(ToastService);

    private assignToOrgStep = viewChild(StepAssignToOrgComponent);

    editUser = signal<AggregatedUser | null>(this.dialogData?.user ?? null);
    availableOrganizations = signal<Organization[]>([]);
    assignableUsers = signal<AssignableUsersResponse[]>([]);
    selectedUserId = signal<number | null>(null);
    customEmail = signal<string | null>(null);
    isSubmitting = signal<boolean>(false);
    isLoadingUsers = signal<boolean>(false);

    editMode = computed(() => this.editUser() !== null);
    existingMemberships = computed<FullMembership[]>(() => this.editUser()?.memberships ?? []);

    userSelectItems = computed<SelectItem<number>[]>(() =>
        this.assignableUsers().map((u) => ({
            name: u.display_name || u.email,
            subtitle: u.display_name ? u.email : undefined,
            value: u.id,
        }))
    );
    userSelectValue = computed<number | string | null>(() => this.selectedUserId() ?? this.customEmail());

    submitDisabled = computed(() => {
        if (this.isSubmitting()) return true;
        if (!this.editMode() && this.selectedUserId() == null && !this.customEmail()) return true;
        const step = this.assignToOrgStep();
        if (!step || step.selectedOrganizations().length === 0) return true;
        return step.hasInvalidRow();
    });

    ngOnInit(): void {
        const currentUser = this.profileService.currentUserSignal();
        if (currentUser) {
            this.availableOrganizations.set(
                currentUser.memberships.map((m) => ({ id: m.organization.id, name: m.organization.name }))
            );
        }
        if (!this.editMode()) {
            this.loadAssignableUsers();
        }
    }

    private loadAssignableUsers(): void {
        this.isLoadingUsers.set(true);
        this.membershipsService
            .getAssignableUsers()
            .pipe(
                takeUntilDestroyed(this.destroyRef),
                finalize(() => this.isLoadingUsers.set(false))
            )
            .subscribe({
                next: (users) => this.assignableUsers.set(users),
                error: () => this.toast.error('Failed to load users.'),
            });
    }

    onUserSelected(value: unknown): void {
        if (typeof value === 'number') {
            this.selectedUserId.set(value);
            this.customEmail.set(null);
            return;
        }

        const email = typeof value === 'string' ? value.trim() : '';

        this.selectedUserId.set(null);
        this.customEmail.set(email || null);
    }

    onClose(): void {
        this.dialogRef.close();
    }

    onSubmit(): void {
        const editing = this.editUser();
        const identity: { user_id?: number; email?: string } = editing
            ? { user_id: editing.id }
            : this.selectedUserId() != null
              ? { user_id: this.selectedUserId()! }
              : this.customEmail()
                ? { email: this.customEmail()! }
                : {};
        if (identity.user_id == null && !identity.email) return;

        this.isSubmitting.set(true);
        const assignments = this.assignToOrgStep()?.getAssignments() ?? [];

        this.performSubmit(identity, assignments)
            .pipe(
                takeUntilDestroyed(this.destroyRef),
                finalize(() => this.isSubmitting.set(false))
            )
            .subscribe({
                next: (success) => {
                    if (!success) return;
                    if (this.editMode()) {
                        this.toast.success('Membership updated successfully.');
                    }
                    this.dialogRef.close(true);
                },
                error: (err: HttpErrorResponse) => this.toast.error(rbacErrorMessage(err, 'Operation failed.')),
            });
    }

    private performSubmit(
        identity: { user_id?: number; email?: string },
        assignments: OrgAssignment[]
    ): Observable<boolean> {
        const user = this.editUser();
        if (user) return this.updateMemberships(user, assignments);
        return this.linkExisting(identity, assignments);
    }

    /** Create mode: link by user_id (existing account) or invite by email per selected org.
     *  Each org is attempted independently; per-org outcomes are toasted. */
    private linkExisting(
        identity: { user_id?: number; email?: string },
        assignments: OrgAssignment[]
    ): Observable<boolean> {
        if (!assignments.length) return of(false);
        const orgNameById = new Map(this.availableOrganizations().map((o) => [o.id, o.name]));
        const ops = assignments.map((a) => {
            const orgName = orgNameById.get(a.orgId) ?? `org ${a.orgId}`;
            return this.membershipsService.create({ org_id: a.orgId, role_id: a.roleId, ...identity }).pipe(
                map(() => ({ ok: true as const, org: orgName })),
                catchError((err: HttpErrorResponse) => of({ ok: false as const, org: orgName, err }))
            );
        });
        return forkJoin(ops).pipe(
            map((results) => {
                const succeeded = results.filter((r) => r.ok);
                const failed = results.filter((r) => !r.ok);
                if (failed.length === 0) {
                    this.toast.success(`Added to ${succeeded.map((r) => r.org).join(', ')}.`);
                } else if (succeeded.length === 0) {
                    this.toast.error(rbacErrorMessage(failed[0].err, 'Failed to add membership.'));
                } else {
                    this.toast.success(`Added to ${succeeded.map((r) => r.org).join(', ')}.`);
                    for (const f of failed) {
                        this.toast.error(`${f.org}: ${rbacErrorMessage(f.err, 'Failed to add.')}`);
                    }
                }
                return succeeded.length > 0;
            })
        );
    }

    /** Edit mode: diff assignments vs existing memberships (add/patch/delete). */
    private updateMemberships(user: AggregatedUser, assignments: OrgAssignment[]): Observable<boolean> {
        const membershipByOrg = new Map(user.memberships.map((m) => [m.organization.id, m]));
        const wantedByOrg = new Map(assignments.map((a) => [a.orgId, a.roleId]));
        const ops: Observable<unknown>[] = [];

        for (const a of assignments) {
            const existing = membershipByOrg.get(a.orgId);
            if (!existing) {
                ops.push(this.membershipsService.create({ org_id: a.orgId, user_id: user.id, role_id: a.roleId }));
            } else if (existing.role.id !== a.roleId) {
                ops.push(this.membershipsService.updateRole(existing.id, { role_id: a.roleId }));
            }
        }
        for (const m of user.memberships) {
            if (!wantedByOrg.has(m.organization.id)) {
                ops.push(this.membershipsService.remove(m.id));
            }
        }

        if (!ops.length) return of(true);
        return forkJoin(ops).pipe(map(() => true));
    }
}
