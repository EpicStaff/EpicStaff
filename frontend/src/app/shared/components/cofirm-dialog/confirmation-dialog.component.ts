import { DIALOG_DATA, DialogModule, DialogRef } from '@angular/cdk/dialog';
import { CommonModule } from '@angular/common';
import { ChangeDetectionStrategy, Component, computed, DestroyRef, inject, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { MatTooltip } from '@angular/material/tooltip';
import { EnterSubmitDirective } from '@shared/directives';
import { Observable } from 'rxjs';

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
    /**
     * `raised`: the lighter `--color-ks-background` surface, a slim rounded caution bar with
     * secondary text, and a Cancel button in the accent colour. Defaults to `default`.
     */
    appearance?: 'default' | 'raised';
    /** Collapsible list of counted items shown under the message, with their total in the header. */
    breakdown?: ConfirmationBreakdown;
    /** Phrase the user must type exactly before the confirm button is enabled. */
    verification?: ConfirmationVerification;
    /** Optional checkbox shown above the action buttons. */
    checkbox?: ConfirmationCheckbox;
    /** Optional HTML shown after the caution block, right above the action buttons. */
    footerMessage?: string;
    /** Optional stream of replacement footer messages, applied as they arrive after the dialog opened.
     *  Unsubscribed when the dialog closes, so it can drive a cancellable request. */
    footerMessageUpdates?: Observable<string>;
}

export interface ConfirmationCheckbox {
    label: string;
    checked?: boolean;
}

@Component({
    selector: 'app-confirmation-dialog',
    imports: [
        MatTooltip,
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

    // `data` and `dialogRef` must stay above the fields below: they read them in their initializers.
    readonly data = inject<ConfirmationDialogData>(DIALOG_DATA);
    private readonly dialogRef = inject<DialogRef<DialogResult>>(DialogRef);
    /** Id of the title; the dialog that opened this one is labelled by it (`ariaLabelledBy`). */
    protected readonly titleId = this.dialogRef.config.ariaLabelledBy ?? null;
    protected readonly footerMessage = signal(this.data.footerMessage ?? '');
    protected readonly checkboxChecked = signal(this.data.checkbox?.checked ?? false);
    protected readonly breakdownListId = `confirmation-breakdown-list-${nextBreakdownListId++}`;
    protected readonly breakdown = this.data.breakdown?.items.length ? this.data.breakdown : null;
    protected readonly breakdownTotal = (this.breakdown?.items ?? []).reduce((sum, item) => sum + item.count, 0);
    protected readonly verificationInputId = `confirmation-verification-input-${nextVerificationInputId++}`;
    protected readonly isConfirmBlocked = computed(
        () => !!this.data.verification && this.typedPhrase() !== this.data.verification.phrase
    );

    private readonly destroyRef = inject(DestroyRef);

    constructor() {
        this.data.footerMessageUpdates?.pipe(takeUntilDestroyed(this.destroyRef)).subscribe((message) => {
            this.footerMessage.set(message);
        });
    }

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
