import { DIALOG_DATA, DialogRef } from '@angular/cdk/dialog';
import { HttpErrorResponse } from '@angular/common/http';
import { ChangeDetectionStrategy, Component, DestroyRef, inject, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { FormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';
import {
    AppSvgIconComponent,
    AvatarUploadComponent,
    ButtonComponent,
    CustomInputComponent,
    HelpTooltipComponent,
    ValidationErrorsComponent,
} from '@shared/components';
import { EnterSubmitDirective } from '@shared/directives';
import { of, switchMap } from 'rxjs';
import { finalize } from 'rxjs/operators';

import { ProfileService } from '../../../../services/auth/profile.service';
import { ToastService } from '../../../../services/notifications';

export interface ProfileEditDialogData {
    name: string;
    email: string;
    avatarUrl: string | null;
}

@Component({
    selector: 'app-profile-edit-dialog',
    templateUrl: './profile-edit-dialog.component.html',
    styleUrls: ['./profile-edit-dialog.component.scss'],
    imports: [
        AppSvgIconComponent,
        AvatarUploadComponent,
        ButtonComponent,
        CustomInputComponent,
        EnterSubmitDirective,
        HelpTooltipComponent,
        ReactiveFormsModule,
        ValidationErrorsComponent,
    ],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class ProfileEditDialogComponent {
    private readonly dialogRef = inject(DialogRef);
    private readonly destroyRef = inject(DestroyRef);
    private readonly fb = inject(FormBuilder);
    readonly data = inject<ProfileEditDialogData>(DIALOG_DATA);
    private readonly profileService = inject(ProfileService);
    private readonly toast = inject(ToastService);

    readonly loading = signal(false);
    readonly shouldDeleteAvatar = signal(false);

    readonly form = this.fb.group({
        full_name: [this.data.name, [Validators.required, Validators.maxLength(50)]],
        email: [{ value: this.data.email, disabled: true }],
        picture: [null as File | null],
    });

    onAvatarChanged(file: File | null): void {
        this.form.patchValue({ picture: file });
        if (file) {
            this.shouldDeleteAvatar.set(false);
        }
    }

    onExistingAvatarRemoved(): void {
        this.shouldDeleteAvatar.set(true);
    }

    onSave(): void {
        this.form.markAllAsTouched();
        if (this.form.invalid) return;

        this.loading.set(true);
        const { full_name, picture } = this.form.getRawValue();

        this.profileService
            .updateCurrentUser({ display_name: full_name! })
            .pipe(
                switchMap(() => {
                    if (picture) {
                        const fd = new FormData();
                        fd.append('avatar', picture);
                        return this.profileService.updateAvatar(fd);
                    }
                    if (this.shouldDeleteAvatar()) {
                        return this.profileService.deleteAvatar();
                    }
                    return of(undefined);
                }),
                takeUntilDestroyed(this.destroyRef),
                finalize(() => this.loading.set(false))
            )
            .subscribe({
                next: () => {
                    this.toast.success('Profile updated successfully.');
                    this.dialogRef.close(true);
                },
                error: (err: HttpErrorResponse) => {
                    this.toast.error(err.error?.message ?? 'Failed to update profile.');
                },
            });
    }

    onCancel(): void {
        this.dialogRef.close(null);
    }
}
