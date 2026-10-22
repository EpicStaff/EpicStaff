import { DIALOG_DATA, DialogRef } from '@angular/cdk/dialog';
import { HttpErrorResponse } from '@angular/common/http';
import { Component, computed, DestroyRef, ElementRef, inject, signal, viewChild } from '@angular/core';
import { takeUntilDestroyed, toSignal } from '@angular/core/rxjs-interop';
import { FormControl, FormGroup, ReactiveFormsModule } from '@angular/forms';
import { AppSvgIconComponent, ButtonComponent } from '@shared/components';
import { extractHttpErrorMessage } from '@shared/utils';

import { ChatBinding, ChatErrorBody, ChatMyAliasResult } from '../../models/chat.model';
import { ChatApiService } from '../../services/chat-api.service';
import { ChatMyAliasesStorageService } from '../../services/chat-my-aliases-storage.service';
import { isSamePublicName, normalizePublicName, publicNameError, validationReason } from '../../utils/public-name.util';

/** The dialog's title, which names it for screen readers (the opener passes it as `ariaLabelledBy`). */
export const MY_DESK_ALIAS_TITLE_ID = 'my-desk-alias-dialog-title';

export interface MyDeskAliasDialogData {
    binding: ChatBinding;
}

// The server's refusals of a name that is valid on its own.
const REFUSALS: Readonly<Record<string, string>> = {
    alias_taken: 'Another operator on this desk already uses this name',
    alias_reserved: "That's the bot's name on this desk",
};

/**
 * The service's checks on an alias, made here first for quick feedback; the service still decides. `alias` is
 * normalised (`normalizePublicName`); blank clears it and is always fine.
 */
export function aliasError(alias: string, binding: ChatBinding): string | null {
    if (!alias) return null;
    const error = publicNameError(alias);
    if (error) return error;
    return isSamePublicName(alias, binding.bot_display_name) ? REFUSALS['alias_reserved'] : null;
}

let nextDialogId = 0;

/**
 * The name the user goes by on one desk: visitors see it on their replies there instead of the desk's operator
 * display name. Saving updates the aliases storage and closes with the server's answer; Cancel, Escape, a backdrop
 * click or an unchanged name close without one. Refusals are said under the field.
 */
@Component({
    selector: 'app-my-desk-alias-dialog',
    imports: [ReactiveFormsModule, AppSvgIconComponent, ButtonComponent],
    templateUrl: './my-desk-alias-dialog.component.html',
    styleUrl: './my-desk-alias-dialog.component.scss',
})
export class MyDeskAliasDialogComponent {
    private readonly aliasInput = viewChild.required<ElementRef<HTMLInputElement>>('aliasInput');

    protected readonly isSaving = signal(false);
    // Client checks speak up after a blur or a save attempt, then as the user types: not on the first keystrokes.
    protected readonly isChecked = signal(false);
    // The server's refusal of the name last sent; gone with the next edit.
    protected readonly refusal = signal<string | null>(null);

    protected readonly binding = inject<MyDeskAliasDialogData>(DIALOG_DATA).binding;
    protected readonly titleId = MY_DESK_ALIAS_TITLE_ID;
    protected readonly inputId = `my-desk-alias-${nextDialogId}`;
    protected readonly hintId = `my-desk-alias-hint-${nextDialogId}`;
    protected readonly errorId = `my-desk-alias-error-${nextDialogId++}`;

    private readonly chatApi = inject(ChatApiService);
    private readonly aliasesStorage = inject(ChatMyAliasesStorageService);
    private readonly dialogRef = inject<DialogRef<ChatMyAliasResult>>(DialogRef);
    private readonly destroyRef = inject(DestroyRef);
    // Declared after the injected fields on purpose: these and the form below start from the stored alias.
    // What the user goes by here now; empty when it is the desk's operator display name.
    private readonly currentAlias = this.aliasesStorage.aliasFor(this.binding.id) ?? '';

    protected readonly form = new FormGroup({
        alias: new FormControl(this.currentAlias, { nonNullable: true }),
    });
    private readonly typed = toSignal(this.form.controls.alias.valueChanges, { initialValue: this.currentAlias });
    protected readonly error = computed(
        () => this.refusal() ?? (this.isChecked() ? aliasError(normalizePublicName(this.typed()), this.binding) : null)
    );

    constructor() {
        this.form.controls.alias.valueChanges
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe(() => this.refusal.set(null));
    }

    save(): void {
        this.isChecked.set(true);
        if (this.isSaving()) return;
        const alias = normalizePublicName(this.form.controls.alias.value);
        if (aliasError(alias, this.binding)) return;
        if (alias === this.currentAlias) {
            this.close();
            return;
        }
        this.isSaving.set(true);
        this.chatApi
            .setMyAlias(this.binding.id, alias || null)
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe({
                next: (result) => {
                    this.aliasesStorage.remember(result);
                    this.dialogRef.close(result);
                },
                error: (error: HttpErrorResponse) => {
                    this.isSaving.set(false);
                    this.refusal.set(refusalMessage(error));
                    // Back to the field, where the refusal is said and can be fixed.
                    this.aliasInput().nativeElement.focus();
                },
            });
    }

    close(): void {
        this.dialogRef.close();
    }
}

/** A refusal in words: the two known conflicts, the validation errors, else the server's message. */
function refusalMessage(error: HttpErrorResponse): string {
    const body = error.error as ChatErrorBody | null;
    const known = body?.code ? REFUSALS[body.code] : undefined;
    if (known) return known;
    const details =
        body?.code === 'validation_error' ? (body.errors ?? []).map(({ message }) => validationReason(message)) : [];
    return details.filter(Boolean).join(' ') || extractHttpErrorMessage(error);
}
