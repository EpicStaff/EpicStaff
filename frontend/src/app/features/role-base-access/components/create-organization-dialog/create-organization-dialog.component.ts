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
import { FormControl, FormGroup, ReactiveFormsModule, Validators } from '@angular/forms';
import {
    ButtonComponent,
    ConfirmationDialogService,
    CustomInputComponent,
    LoadingSpinnerComponent,
    NumberStepperComponent,
    SelectComponent,
    SelectItem,
    ValidationErrorsComponent,
} from '@shared/components';
import { EnterSubmitDirective, ServerErrorsDirective, ServerErrorsRef } from '@shared/directives';
import { notWhitespaceValidator } from '@shared/form-validators';
import {
    CreateOrganizationRequest,
    GetOrganizationResponse,
    OrganizationRetention,
    OrganizationRetentionUpdate,
    RetentionDataType,
} from '@shared/models';
import { catchError, EMPTY, finalize, map, Observable, of, switchMap, tap, throwError } from 'rxjs';

import { ProfileService } from '../../../../services/auth/profile.service';
import { ToastService } from '../../../../services/notifications';
import { AdminOrganizationsService } from '../../services/admin/organizations.service';
import { OrganizationsStorageService } from '../../services/admin/organizations-storage.service';
import {
    buildRetentionItems,
    buildRetentionUpdate,
    describeRetentionLowerings,
    findRetentionLowerings,
    rbacErrorMessage,
    RetentionChoice,
    RetentionField,
    toRetentionChoice,
    USE_DEFAULT_RETENTION,
} from '../../utils';
import { OrgMembersEditorComponent } from './org-members-editor/org-members-editor.component';

type RetentionUnit = 'unlimited' | 'years' | 'months' | 'days';

const DAYS_PER_UNIT: Record<RetentionUnit, number> = { unlimited: 0, years: 365, months: 30, days: 1 };
const MAX_RETENTION_DAYS = 36_500;
// The stepper's starting value when the user switches from Unlimited to a unit.
const DEFAULT_RETENTION_AMOUNT = 1;

interface RetentionColumnConfig {
    type: RetentionDataType;
    label: string;
    hint?: string;
}

let nextDialogId = 0;

const RETENTION_COLUMNS: RetentionColumnConfig[] = [
    { type: 'sessions', label: 'Sessions' },
    { type: 'audit', label: 'Audit events', hint: 'Changes apply to audit events recorded from now on.' },
    { type: 'conversations', label: 'Conversations' },
];

@Component({
    selector: 'app-create-organization-dialog',
    templateUrl: './create-organization-dialog.component.html',
    styleUrls: ['./create-organization-dialog.component.scss'],
    imports: [
        ButtonComponent,
        CustomInputComponent,
        EnterSubmitDirective,
        LoadingSpinnerComponent,
        NumberStepperComponent,
        OrgMembersEditorComponent,
        ReactiveFormsModule,
        SelectComponent,
        ServerErrorsDirective,
        ValidationErrorsComponent,
    ],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class CreateOrganizationDialogComponent implements OnInit {
    private destroyRef = inject(DestroyRef);
    private toast = inject(ToastService);
    private dialogRef = inject(DialogRef);
    private confirmation = inject(ConfirmationDialogService);
    private organizationStorage = inject(OrganizationsStorageService);
    private organizationsApi = inject(AdminOrganizationsService);
    private profileService = inject(ProfileService);
    private dialogData = inject<GetOrganizationResponse>(DIALOG_DATA, { optional: true });
    private readonly retentionLabelIdPrefix = `organization-retention-label-${nextDialogId++}`;

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

    // Retention has its own endpoint and its policy can only be read through an existing organization,
    // so the row is edit-only; a new organization starts on the instance defaults.
    readonly retentionForm = new FormGroup<Record<RetentionField, FormControl<RetentionChoice>>>({
        sessions_days: new FormControl<RetentionChoice>(USE_DEFAULT_RETENTION, { nonNullable: true }),
        audit_days: new FormControl<RetentionChoice>(USE_DEFAULT_RETENTION, { nonNullable: true }),
        conversations_days: new FormControl<RetentionChoice>(USE_DEFAULT_RETENTION, { nonNullable: true }),
    });
    readonly retentionErrorsRef = new ServerErrorsRef();
    readonly retention = signal<OrganizationRetention | null>(null);
    readonly isRetentionLoading = signal(false);
    readonly retentionColumns = computed(() => {
        const retention = this.retention();
        if (!retention) return [];
        return RETENTION_COLUMNS.map((column) => ({
            ...column,
            labelId: `${this.retentionLabelIdPrefix}-${column.type}`,
            control: this.retentionForm.controls[`${column.type}_days`],
            items: buildRetentionItems(retention, column.type),
        }));
    });

    isSubmitting = signal(false);

    readonly submitDisabled = computed(
        () => this.isSubmitting() || this.isNameInvalid() || (this.membersEditor()?.hasInvalidRow() ?? false)
    );

    ngOnInit(): void {
        if (this.organizationId === null) return;

        this.isRetentionLoading.set(true);
        this.organizationsApi
            .getRetention(this.organizationId)
            .pipe(
                takeUntilDestroyed(this.destroyRef),
                finalize(() => this.isRetentionLoading.set(false))
            )
            .subscribe({
                next: (retention) => this.applyRetention(retention),
                error: (err: HttpErrorResponse) =>
                    this.toast.error(rbacErrorMessage(err, 'Failed to load data retention.')),
            });
    }

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

        const retention = this.retention();
        const retentionUpdate = retention ? buildRetentionUpdate(retention, this.retentionForm.getRawValue()) : null;
        const lowerings = retention ? findRetentionLowerings(retention, retentionUpdate) : [];
        if (lowerings.length === 0) {
            this.save(retentionUpdate);
            return;
        }

        // blocks Save and Enter while the confirmation is open
        this.isSubmitting.set(true);
        this.confirmation
            .confirm({
                title: 'Lower data retention?',
                message: describeRetentionLowerings(lowerings),
                confirmText: 'Save',
                cancelText: 'Cancel',
                type: 'danger',
            })
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe((result) => {
                if (result === true) {
                    this.save(retentionUpdate);
                } else {
                    this.isSubmitting.set(false);
                }
            });
    }

    private save(retentionUpdate: OrganizationRetentionUpdate | null): void {
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
                switchMap((org) => this.saveRetention(org.id, retentionUpdate).pipe(map(() => org))),
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

    // A failure stops the chain before the members are committed and keeps the dialog open, like a failed
    // organization update; saving again re-sends the same name, so it is safe to retry. Field errors are shown
    // inline only, like the other ServerErrorsDirective forms; the toast would repeat the raw backend message.
    private saveRetention(
        organizationId: number,
        update: OrganizationRetentionUpdate | null
    ): Observable<OrganizationRetention | null> {
        if (!update) return of(null);

        this.retentionErrorsRef.clear();
        return this.organizationsApi.updateRetention(organizationId, update).pipe(
            tap((retention) => this.applyRetention(retention)),
            catchError((err: HttpErrorResponse) => {
                const fieldErrors = err.validationErrors ?? [];
                const isShownInline =
                    fieldErrors.length > 0 && fieldErrors.every((error) => error.field in this.retentionForm.controls);
                if (isShownInline) {
                    this.retentionErrorsRef.setErrors(fieldErrors);
                    return EMPTY;
                }
                return throwError(() => err);
            })
        );
    }

    private applyRetention(retention: OrganizationRetention): void {
        this.retention.set(retention);
        this.retentionForm.setValue({
            sessions_days: toRetentionChoice(retention.sessions_days),
            audit_days: toRetentionChoice(retention.audit_days),
            conversations_days: toRetentionChoice(retention.conversations_days),
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
