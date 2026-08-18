import { DIALOG_DATA, DialogRef } from '@angular/cdk/dialog';
import { HttpErrorResponse } from '@angular/common/http';
import { ChangeDetectionStrategy, Component, computed, DestroyRef, inject, OnInit, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { FormControl, FormGroup, ReactiveFormsModule, Validators } from '@angular/forms';
import {
    AppSvgIconComponent,
    ButtonComponent,
    CustomInputComponent,
    HelpTooltipComponent,
    SelectComponent,
    SelectItem,
    ValidationErrorsComponent,
} from '@shared/components';
import { ActionCode, GetRoleResponse, ResourceCode } from '@shared/models';
import { finalize, switchMap } from 'rxjs';

import { PermissionsService } from '../../../../services/auth/permissions.service';
import { ToastService } from '../../../../services/notifications';
import { OrganizationsStorageService } from '../../services/admin/organizations-storage.service';
import { RolesService } from '../../services/admin/roles.service';

export interface CopyRoleDialogData {
    source: GetRoleResponse;
}

@Component({
    selector: 'app-copy-role-dialog',
    templateUrl: './copy-role-dialog.component.html',
    styleUrls: ['./copy-role-dialog.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
    imports: [
        AppSvgIconComponent,
        ButtonComponent,
        CustomInputComponent,
        HelpTooltipComponent,
        ReactiveFormsModule,
        SelectComponent,
        ValidationErrorsComponent,
    ],
})
export class CopyRoleDialogComponent implements OnInit {
    private dialogRef = inject<DialogRef<'copied' | undefined>>(DialogRef);
    private data = inject<CopyRoleDialogData>(DIALOG_DATA);
    private permissionsService = inject(PermissionsService);
    private rolesService = inject(RolesService);
    private orgStorage = inject(OrganizationsStorageService);
    private toast = inject(ToastService);
    private destroyRef = inject(DestroyRef);

    readonly source = this.data.source;

    readonly form = new FormGroup({
        name: new FormControl(this.source.name, {
            nonNullable: true,
            validators: [Validators.required, Validators.minLength(3), Validators.maxLength(30)],
        }),
    });

    readonly targetOrgId = signal<number | null>(null);
    readonly orgOptions = signal<SelectItem<number>[]>([]);
    readonly isSubmitting = signal(false);

    readonly canSubmit = computed(() => !this.isSubmitting() && this.form.valid && this.targetOrgId() !== null);

    ngOnInit(): void {
        this.loadCreatableOrgs();
    }

    private loadCreatableOrgs(): void {
        if (this.permissionsService.isSuperadmin) {
            this.orgStorage
                .getOrganizations()
                .pipe(takeUntilDestroyed(this.destroyRef))
                .subscribe((orgs) => {
                    const options = orgs.filter((o) => o.is_active).map((o) => ({ name: o.name, value: o.id }));
                    this.orgOptions.set(options);
                    this.preselectTargetOrg(options);
                });
            return;
        }

        const creatable = this.permissionsService.orgsWith(ResourceCode.Roles, ActionCode.Create);
        const options: SelectItem<number>[] = creatable.map((o) => ({ name: o.name, value: o.id }));
        this.orgOptions.set(options);
        this.preselectTargetOrg(options);
    }

    /** Prefer the source role's own org as the default target when available; otherwise auto-pick if only one option. */
    private preselectTargetOrg(options: SelectItem<number>[]): void {
        if (this.targetOrgId() !== null) return;
        const sourceOrgId = this.source.org_id;
        if (sourceOrgId !== null && options.some((o) => o.value === sourceOrgId)) {
            this.targetOrgId.set(sourceOrgId);
            return;
        }
        if (options.length === 1) this.targetOrgId.set(options[0].value);
    }

    onTargetOrgChanged(value: unknown): void {
        this.targetOrgId.set(typeof value === 'number' ? value : null);
    }

    onCopy(): void {
        if (!this.canSubmit()) {
            this.form.markAllAsTouched();
            return;
        }
        const name = this.form.controls.name.value.trim();
        const orgId = this.targetOrgId()!;

        this.isSubmitting.set(true);
        // Fetch the fresh source (in case anything changed since the list load) then create.
        this.rolesService
            .getRoleById(this.source.id)
            .pipe(
                switchMap((src) =>
                    this.rolesService.createRole({
                        org_id: orgId,
                        name,
                        description: src.description,
                        permissions: src.permissions,
                    })
                ),
                finalize(() => this.isSubmitting.set(false)),
                takeUntilDestroyed(this.destroyRef)
            )
            .subscribe({
                next: () => {
                    this.toast.success('Role duplicated');
                    this.dialogRef.close('copied');
                },
                error: (err: HttpErrorResponse) => this.handleError(err),
            });
    }

    private handleError(err: HttpErrorResponse): void {
        const code: string | undefined = err.error?.code;
        if (code === 'role_name_conflict') {
            this.form.controls.name.setErrors({ conflict: true });
            return;
        }
        if (code === 'permission_escalation_denied') {
            this.toast.error("You can't duplicate this role — it grants permissions you don't have in the target org.");
            return;
        }
        this.toast.error(err.error?.message ?? 'Failed to duplicate role');
    }

    onCancel(): void {
        this.dialogRef.close();
    }
}
