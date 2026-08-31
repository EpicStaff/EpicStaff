import { DIALOG_DATA, DialogRef } from '@angular/cdk/dialog';
import { HttpErrorResponse } from '@angular/common/http';
import { ChangeDetectionStrategy, Component, computed, DestroyRef, inject, signal, viewChild } from '@angular/core';
import { takeUntilDestroyed, toSignal } from '@angular/core/rxjs-interop';
import { FormControl, ReactiveFormsModule, Validators } from '@angular/forms';
import { ButtonComponent, CustomInputComponent, ValidationErrorsComponent } from '@shared/components';
import { notWhitespaceValidator } from '@shared/form-validators';
import { CreateOrganizationRequest, GetOrganizationResponse } from '@shared/models';
import { finalize, map, Observable, switchMap } from 'rxjs';

import { ProfileService } from '../../../../services/auth/profile.service';
import { ToastService } from '../../../../services/notifications';
import { OrganizationsStorageService } from '../../services/admin/organizations-storage.service';
import { rbacErrorMessage } from '../../utils/rbac-error-messages.util';
import { OrgMembersEditorComponent } from './org-members-editor/org-members-editor.component';

@Component({
    selector: 'app-create-organization-dialog',
    templateUrl: './create-organization-dialog.component.html',
    styleUrls: ['./create-organization-dialog.component.scss'],
    imports: [
        ButtonComponent,
        ReactiveFormsModule,
        ValidationErrorsComponent,
        CustomInputComponent,
        OrgMembersEditorComponent,
    ],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class CreateOrganizationDialogComponent {
    private destroyRef = inject(DestroyRef);
    private toast = inject(ToastService);
    private dialogRef = inject(DialogRef);
    private organizationStorage = inject(OrganizationsStorageService);
    private profileService = inject(ProfileService);
    private dialogData = inject<GetOrganizationResponse>(DIALOG_DATA, { optional: true });

    readonly isEditMode = !!this.dialogData;
    readonly organizationId = this.dialogData?.id ?? null;

    private membersEditor = viewChild(OrgMembersEditorComponent);

    orgNameControl = new FormControl(this.dialogData?.name ?? '', [
        notWhitespaceValidator(),
        Validators.required,
        Validators.minLength(3),
        Validators.maxLength(50),
    ]);
    private isNameInvalid = toSignal(this.orgNameControl.statusChanges.pipe(map(() => this.orgNameControl.invalid)), {
        initialValue: this.orgNameControl.invalid,
    });

    isSubmitting = signal(false);

    readonly submitDisabled = computed(
        () => this.isSubmitting() || this.isNameInvalid() || (this.membersEditor()?.hasInvalidRow() ?? false)
    );

    onCancel(): void {
        this.dialogRef.close();
    }

    onSubmit(): void {
        if (this.orgNameControl.invalid) {
            this.orgNameControl.markAsTouched();
            return;
        }

        this.isSubmitting.set(true);

        const request: CreateOrganizationRequest = { name: this.orgNameControl.value! };
        const orgAction$: Observable<GetOrganizationResponse> = this.isEditMode
            ? this.organizationStorage.updateOrganization(this.organizationId!, request)
            : this.organizationStorage.createOrganization(request);

        orgAction$
            .pipe(
                switchMap((org) => this.membersEditor()!.commit(org.id)),
                switchMap((failures) => this.profileService.getCurrentUser().pipe(map(() => failures))),
                takeUntilDestroyed(this.destroyRef),
                finalize(() => this.isSubmitting.set(false))
            )
            .subscribe({
                next: (failures) => {
                    if (failures === 0) {
                        this.toast.success(
                            this.isEditMode
                                ? 'Organization updated successfully.'
                                : 'Organization created successfully.'
                        );
                    }
                    this.dialogRef.close(true);
                },
                error: (err: HttpErrorResponse) => this.toast.error(rbacErrorMessage(err, 'Operation failed.')),
            });
    }
}
