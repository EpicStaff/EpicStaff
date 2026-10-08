import { DIALOG_DATA, DialogModule, DialogRef } from '@angular/cdk/dialog';
import { CommonModule } from '@angular/common';
import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import { EnterSubmitDirective } from '@shared/directives';

import { AppIconComponent } from '../app-icon/app-icon.component';
import { AppSvgIconComponent } from '../app-svg-icon/app-svg-icon.component';
import { IconButtonComponent } from '../buttons/icon-button/icon-button.component';
import { CheckboxComponent } from '../checkbox/checkbox.component';

export interface DialogResult {
    action: 'confirm' | 'cancel' | 'close';
    checked?: boolean;
}

let nextBreakdownListId = 0;
let nextVerificationInputId = 0;

export interface ConfirmationBreakdownItem {
    label: string;
    count: number;
}

export interface ConfirmationBreakdown {
    title: string;
    items: ConfirmationBreakdownItem[];
}

export interface ConfirmationVerification {
    phrase: string;
}

export interface ConfirmationDialogData {
    title: string;
    message: string;
    confirmText?: string;
    cancelText?: string;
    type?: 'warning' | 'danger' | 'info';
    caution?: string;
    cautionTitle?: string;
    isShownBorder?: boolean;
    /** Hide the confirm button entirely -- for informational dialogs the caller
     *  cannot actually proceed with (e.g. blocked by a missing permission).
     *  The cancel button then acts as a plain close. */
    hideConfirm?: boolean;
    /** Collapsible list of counted items shown under the message, with their total in the header. */
    breakdown?: ConfirmationBreakdown;
    /** Phrase the user must type exactly before the confirm button is enabled. */
    verification?: ConfirmationVerification;
    /** Optional checkbox shown above the action buttons. */
    checkbox?: ConfirmationCheckbox;
}

export interface ConfirmationCheckbox {
    label: string;
    checked?: boolean;
}

@Component({
    selector: 'app-confirmation-dialog',
    imports: [
        CommonModule,
        DialogModule,
        IconButtonComponent,
        AppSvgIconComponent,
        AppIconComponent,
        CheckboxComponent,
        EnterSubmitDirective,
    ],
    templateUrl: './confirmation-dialog.component.html',
    changeDetection: ChangeDetectionStrategy.Eager,
    styleUrls: ['./confirmation-dialog.component.scss'],
})
export class ConfirmationDialogComponent {
    protected readonly isBreakdownExpanded = signal(false);
    protected readonly typedPhrase = signal('');

    // `data` must stay above the fields below: they read it in their initializers.
    readonly data = inject<ConfirmationDialogData>(DIALOG_DATA);
    protected readonly checkboxChecked = signal(this.data.checkbox?.checked ?? false);
    protected readonly breakdownListId = `confirmation-breakdown-list-${nextBreakdownListId++}`;
    protected readonly breakdown = this.data.breakdown?.items.length ? this.data.breakdown : null;
    protected readonly breakdownTotal = (this.breakdown?.items ?? []).reduce((sum, item) => sum + item.count, 0);
    protected readonly verificationInputId = `confirmation-verification-input-${nextVerificationInputId++}`;
    protected readonly isConfirmBlocked = computed(
        () => !!this.data.verification && this.typedPhrase() !== this.data.verification.phrase
    );

    private readonly dialogRef = inject<DialogRef<DialogResult>>(DialogRef);

    toggleBreakdown(): void {
        this.isBreakdownExpanded.update((isExpanded) => !isExpanded);
    }

    onPhraseInput(event: Event): void {
        this.typedPhrase.set((event.target as HTMLInputElement).value);
    }

    protected onEnterSubmit(): void {
        // prevent from performing actions like delete by pressing enter
        if (this.data.type === 'danger') return;
        this.onConfirm();
    }

    onCancel(): void {
        this.dialogRef.close({ action: 'cancel' });
    }

    onConfirm(): void {
        if (this.isConfirmBlocked()) return;
        this.dialogRef.close({ action: 'confirm', checked: this.checkboxChecked() });
    }

    onClose(): void {
        this.dialogRef.close({ action: 'close' });
    }
}
