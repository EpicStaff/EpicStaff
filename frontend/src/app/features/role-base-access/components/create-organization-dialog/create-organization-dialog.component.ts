import { DIALOG_DATA, DialogRef } from '@angular/cdk/dialog';
import { HttpErrorResponse } from '@angular/common/http';
import { ChangeDetectionStrategy, Component, computed, DestroyRef, inject, signal, viewChild } from '@angular/core';
import { takeUntilDestroyed, toSignal } from '@angular/core/rxjs-interop';
import { FormControl, ReactiveFormsModule, Validators } from '@angular/forms';
import {
    ButtonComponent,
    CustomInputComponent,
    NumberStepperComponent,
    SelectComponent,
    SelectItem,
    ValidationErrorsComponent,
} from '@shared/components';
import { EnterSubmitDirective } from '@shared/directives';
import { notWhitespaceValidator } from '@shared/form-validators';
import { CreateOrganizationRequest, GetOrganizationResponse } from '@shared/models';
import { finalize, map, Observable, of, switchMap } from 'rxjs';

import { ProfileService } from '../../../../services/auth/profile.service';
import { ToastService } from '../../../../services/notifications';
import { OrganizationsStorageService } from '../../services/admin/organizations-storage.service';
import { rbacErrorMessage } from '../../utils';
import { OrgMembersEditorComponent } from './org-members-editor/org-members-editor.component';

type RetentionUnit = 'unlimited' | 'years' | 'months' | 'days';

const DAYS_PER_UNIT: Record<RetentionUnit, number> = { unlimited: 0, years: 365, months: 30, days: 1 };
const MAX_RETENTION_DAYS = 36_500;
// The stepper's starting value when the user switches from Unlimited to a unit.
const DEFAULT_RETENTION_AMOUNT = 1;

@Component({
    selector: 'app-create-organization-dialog',
    templateUrl: './create-organization-dialog.component.html',
    styleUrls: ['./create-organization-dialog.component.scss'],
    imports: [
        ButtonComponent,
        CustomInputComponent,
        EnterSubmitDirective,
        NumberStepperComponent,
        OrgMembersEditorComponent,
        ReactiveFormsModule,
        SelectComponent,
        ValidationErrorsComponent,
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

    private readonly savedRetentionDays = this.dialogData?.config?.audit_retention_days ?? 0;
    readonly retentionUnit = signal<RetentionUnit>(splitRetentionDays(this.savedRetentionDays).unit);
    readonly retentionAmount = signal(splitRetentionDays(this.savedRetentionDays).amount);
    readonly retentionUnitItems: SelectItem<RetentionUnit>[] = [
        { name: 'Unlimited', value: 'unlimited' },
        { name: 'Years', value: 'years' },
        { name: 'Months', value: 'months' },
        { name: 'Days', value: 'days' },
    ];
    readonly maxRetentionAmount = computed(() =>
        Math.floor(MAX_RETENTION_DAYS / (DAYS_PER_UNIT[this.retentionUnit()] || 1))
    );
    // the stepper clamps only on blur, so a typed 0 submitted with Enter or 400 days switched to years is clamped here
    readonly clampedRetentionAmount = computed(() =>
        Math.min(Math.max(this.retentionAmount(), 1), this.maxRetentionAmount())
    );

    isSubmitting = signal(false);

    readonly submitDisabled = computed(
        () => this.isSubmitting() || this.isNameInvalid() || (this.membersEditor()?.hasInvalidRow() ?? false)
    );

    // the stepper emits null while the field is being retyped; it falls back to its min on blur
    setRetentionAmount(amount: number | null): void {
        if (amount !== null) {
            this.retentionAmount.set(amount);
        }
    }

    onCancel(): void {
        this.dialogRef.close();
    }

    onSubmit(): void {
        if (this.orgNameControl.invalid) {
            this.orgNameControl.markAsTouched();
            return;
        }

        this.isSubmitting.set(true);

        const request: CreateOrganizationRequest = {
            name: this.orgNameControl.value!,
            // Unlimited is 0 days per unit, so it sends 0
            audit_retention_days: this.clampedRetentionAmount() * DAYS_PER_UNIT[this.retentionUnit()],
        };
        const orgAction$: Observable<GetOrganizationResponse> = this.isEditMode
            ? this.organizationStorage.updateOrganization(this.organizationId!, request)
            : this.organizationStorage.createOrganization(request);

        orgAction$
            .pipe(
                switchMap((org) => this.membersEditor()?.commit(org.id) ?? of(0)),
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

// The backend stores days only; show them in the largest unit that divides evenly: 730 → 2 years, 90 → 3 months, 45 → 45 days.
function splitRetentionDays(days: number): { unit: RetentionUnit; amount: number } {
    if (days === 0) {
        return { unit: 'unlimited', amount: DEFAULT_RETENTION_AMOUNT };
    }
    if (days % DAYS_PER_UNIT.years === 0) {
        return { unit: 'years', amount: days / DAYS_PER_UNIT.years };
    }
    if (days % DAYS_PER_UNIT.months === 0) {
        return { unit: 'months', amount: days / DAYS_PER_UNIT.months };
    }
    return { unit: 'days', amount: days };
}
