import { DIALOG_DATA, DialogRef } from '@angular/cdk/dialog';
import { Component, computed, inject, signal } from '@angular/core';
import {
    AppSvgIconComponent,
    ButtonComponent,
    NumberStepperComponent,
    SelectComponent,
    SelectItem,
} from '@shared/components';

import {
    AUDIT_HISTORY_DAYS_PER_UNIT,
    auditHistoryRangeToDays,
    AuditHistoryUnit,
    MAX_AUDIT_HISTORY_DAYS,
    splitAuditHistoryDays,
} from '../../utils';

/** Opens with the stored days; closes with the new days on Save Range, undefined on Cancel. */
@Component({
    selector: 'app-audit-history-dialog',
    templateUrl: './audit-history-dialog.component.html',
    styleUrls: ['./audit-history-dialog.component.scss'],
    imports: [AppSvgIconComponent, ButtonComponent, NumberStepperComponent, SelectComponent],
})
export class AuditHistoryDialogComponent {
    // above the signals, which are seeded from it
    private readonly initialRange = splitAuditHistoryDays(inject<number>(DIALOG_DATA));

    protected readonly unit = signal<AuditHistoryUnit>(this.initialRange.unit);
    protected readonly amount = signal(this.initialRange.amount);
    protected readonly maxAmount = computed(() =>
        Math.floor(MAX_AUDIT_HISTORY_DAYS / (AUDIT_HISTORY_DAYS_PER_UNIT[this.unit()] || 1))
    );
    // the stepper clamps only on blur, and switching 400 days to years overshoots the max, so clamp here
    protected readonly clampedAmount = computed(() => Math.min(Math.max(this.amount(), 1), this.maxAmount()));

    protected readonly unitItems: SelectItem<AuditHistoryUnit>[] = [
        { name: 'Unlimited', value: 'unlimited' },
        { name: 'Years', value: 'years' },
        { name: 'Months', value: 'months' },
        { name: 'Days', value: 'days' },
    ];

    private readonly dialogRef = inject<DialogRef<number>>(DialogRef);

    // the stepper emits null while the field is being retyped; it falls back to its min on blur
    protected setAmount(amount: number | null): void {
        if (amount !== null) {
            this.amount.set(amount);
        }
    }

    protected onSave(): void {
        this.dialogRef.close(auditHistoryRangeToDays({ unit: this.unit(), amount: this.clampedAmount() }));
    }

    protected onCancel(): void {
        this.dialogRef.close();
    }
}
