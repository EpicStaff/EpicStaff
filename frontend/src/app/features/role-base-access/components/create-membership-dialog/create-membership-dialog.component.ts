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
import { takeUntilDestroyed, toSignal } from '@angular/core/rxjs-interop';
import { FormControl, ReactiveFormsModule, Validators } from '@angular/forms';
import {
    ButtonComponent,
    CustomInputComponent,
    HelpTooltipComponent,
    ValidationErrorsComponent,
} from '@shared/components';
import { FullMembership, Organization } from '@shared/models';
import { concat, forkJoin, map, Observable, of, toArray } from 'rxjs';
import { finalize } from 'rxjs/operators';

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
    imports: [
        ButtonComponent,
        StepAssignToOrgComponent,
        ReactiveFormsModule,
        CustomInputComponent,
        HelpTooltipComponent,
        ValidationErrorsComponent,
    ],
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
    isSubmitting = signal<boolean>(false);

    editMode = computed(() => this.editUser() !== null);
    existingMemberships = computed<FullMembership[]>(() => this.editUser()?.memberships ?? []);

    emailControl = new FormControl<string>('', {
        nonNullable: true,
        validators: [Validators.required, Validators.email],
    });

    private isEmailValid = toSignal(this.emailControl.statusChanges.pipe(map(() => !this.emailControl.invalid)), {
        initialValue: !this.emailControl.invalid,
    });

    submitDisabled = computed(() => {
        if (!this.isEmailValid() || this.isSubmitting()) return true;
        const step = this.assignToOrgStep();
        if (!step || step.selectedOrganizations().length === 0) return true;
        return step.hasInvalidRow();
    });

    constructor() {
        const user = this.editUser();
        if (user) {
            this.emailControl.setValue(user.email);
            this.emailControl.disable();
        }
    }

    ngOnInit(): void {
        const currentUser = this.profileService.currentUserSignal();
        if (currentUser) {
            this.availableOrganizations.set(
                currentUser.memberships.map((m) => ({ id: m.organization.id, name: m.organization.name }))
            );
        }
    }

    onClose(): void {
        this.dialogRef.close();
    }

    onSubmit(): void {
        if (this.emailControl.invalid) return;

        this.isSubmitting.set(true);
        const email = this.emailControl.getRawValue();
        const assignments = this.assignToOrgStep()?.getAssignments() ?? [];

        this.performSubmit(email, assignments)
            .pipe(
                takeUntilDestroyed(this.destroyRef),
                finalize(() => this.isSubmitting.set(false))
            )
            .subscribe({
                next: (success) => {
                    if (!success) return;
                    this.toast.success(
                        this.editMode() ? 'Membership updated successfully.' : 'Membership created successfully.'
                    );
                    this.dialogRef.close(true);
                },
                error: (err: HttpErrorResponse) => this.toast.error(rbacErrorMessage(err, 'Operation failed.')),
            });
    }

    trimEmail(): void {
        if (this.emailControl.value) {
            this.emailControl.setValue(this.emailControl.value.trim());
        }
    }

    private performSubmit(email: string, assignments: OrgAssignment[]): Observable<boolean> {
        const user = this.editUser();
        if (user) return this.updateMemberships(user, assignments);
        return this.linkExistingByEmail(email, assignments);
    }

    /** Create mode: link existing account by email per selected org. */
    private linkExistingByEmail(email: string, assignments: OrgAssignment[]): Observable<boolean> {
        if (!assignments.length) return of(false);
        const ops = assignments.map((a) =>
            this.membershipsService.create({ org_id: a.orgId, email, role_id: a.roleId })
        );
        return concat(...ops).pipe(
            toArray(),
            map(() => true)
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
