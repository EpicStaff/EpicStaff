import { DIALOG_DATA, DialogRef } from '@angular/cdk/dialog';
import { hasModifierKey } from '@angular/cdk/keycodes';
import { HttpErrorResponse } from '@angular/common/http';
import { Component, computed, DestroyRef, inject, OnInit, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import {
    AbstractControl,
    FormControl,
    FormControlStatus,
    FormGroup,
    ReactiveFormsModule,
    ValidationErrors,
} from '@angular/forms';
import { MatTooltip } from '@angular/material/tooltip';
import { AppSvgIconComponent, ButtonComponent, CustomInputComponent } from '@shared/components';
import { filter, merge, tap } from 'rxjs';

import { ToastService } from '../../../../services/notifications';
import { PluginDetail, PluginSecretSlot, PluginSecretValues, PluginSummary } from '../../models/plugin.model';
import { PluginsStoreService } from '../../services/plugins-store.service';
import { pluginStatusLabel } from '../../utils/plugin-display.util';
import { PluginErrorView, toPluginErrorView } from '../../utils/plugin-error.util';
import { PLUGIN_SECRET_VALUE_MAX_LENGTH, pluginSecretValueValidators } from '../../utils/plugin-secret-value.util';
import { PluginSecretDestinationsComponent } from '../plugin-secret-destinations/plugin-secret-destinations.component';

export interface PluginSecretsDialogData {
    plugin: PluginSummary;
}

type SecretsForm = FormGroup<Record<string, FormControl<string>>>;

/**
 * Re-enters the values of a plugin's secret slots, for example a wrong API key that made indexing fail.
 * When the plugin still needs attention after the save, it offers to retry preparing its knowledge.
 *
 * The values live only in the form: it is cleared after a successful save and whenever the dialog
 * closes, and they are never shown back, logged or kept anywhere else.
 */
@Component({
    selector: 'app-plugin-secrets-dialog',
    imports: [
        ReactiveFormsModule,
        AppSvgIconComponent,
        ButtonComponent,
        CustomInputComponent,
        MatTooltip,
        PluginSecretDestinationsComponent,
    ],
    templateUrl: './plugin-secrets-dialog.component.html',
    styleUrls: ['./plugin-secrets-dialog.component.scss'],
})
export class PluginSecretsDialogComponent implements OnInit {
    protected readonly saving = signal(false);
    protected readonly retrying = signal(false);
    protected readonly error = signal<PluginErrorView | null>(null);
    /**
     * The plugin as the save (and any retry after it) returned it, set only while it still needs
     * attention: the dialog then offers to retry instead of showing the form.
     */
    protected readonly pluginToRetry = signal<PluginDetail | null>(null);
    private readonly formStatus = signal<FormControlStatus>('INVALID');

    /** Closing is blocked while a request is on its way, as in the install and delete dialogs. */
    protected readonly busy = computed(() => this.saving() || this.retrying());
    protected readonly canSave = computed(() => this.formStatus() === 'VALID' && !this.saving());

    protected readonly data: PluginSecretsDialogData = inject(DIALOG_DATA);
    /** "Needs attention: <reason>" when the dialog opened for a plugin that needs attention. */
    protected readonly attentionMessage: string | null =
        this.data.plugin.status === 'needs_attention' ? pluginStatusLabel(this.data.plugin) : null;
    protected readonly slots: PluginSecretSlot[] = this.data.plugin.secret_slots;
    protected readonly form: SecretsForm = buildSecretsForm(this.slots);
    protected readonly secretValueMaxLength = PLUGIN_SECRET_VALUE_MAX_LENGTH;

    private readonly dialogRef = inject(DialogRef<PluginDetail | undefined>);
    private readonly pluginsStore = inject(PluginsStoreService);
    private readonly toastService = inject(ToastService);
    private readonly destroyRef = inject(DestroyRef);

    ngOnInit(): void {
        this.routeDismissThroughClose();
        this.trackFormStatus();
        // A close the dialog can't intercept (closeAll, navigation) still destroys the component.
        this.destroyRef.onDestroy(() => this.clearSecretValues());
    }

    save(): void {
        if (!this.canSave()) return;
        this.saving.set(true);
        this.error.set(null);
        // No retry here: once the values are saved, the admin chooses whether to retry.
        this.pluginsStore
            .updateSecrets(this.data.plugin.id, { secrets: this.enteredSecrets(), retry_indexing: false })
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe({
                next: (plugin) => {
                    this.saving.set(false);
                    this.clearSecretValues();
                    if (plugin.status === 'needs_attention') {
                        this.pluginToRetry.set(plugin);
                        return;
                    }
                    this.toastService.success(`Secrets of ${plugin.name} updated`);
                    this.dialogRef.close(plugin);
                },
                error: (error: HttpErrorResponse) => {
                    this.saving.set(false);
                    this.error.set(toPluginErrorView(error, "The secrets couldn't be saved."));
                },
            });
    }

    retry(): void {
        const plugin = this.pluginToRetry();
        if (!plugin || this.retrying()) return;
        this.retrying.set(true);
        this.error.set(null);
        this.pluginsStore
            .retry(plugin.id)
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe({
                next: (result) => {
                    this.retrying.set(false);
                    if (result.status === 'needs_attention') {
                        // Indexing couldn't even start (e.g. knowledge service down): stay, show the new reason.
                        this.pluginToRetry.set(result);
                        this.error.set({
                            code: null,
                            message: "Preparing knowledge couldn't start.",
                            details: result.status_reason ? [result.status_reason] : [],
                        });
                        return;
                    }
                    this.toastService.success('Preparing knowledge again');
                    this.dialogRef.close(result);
                },
                error: (error: HttpErrorResponse) => {
                    this.retrying.set(false);
                    this.error.set(toPluginErrorView(error, "Preparing knowledge couldn't be restarted."));
                },
            });
    }

    close(): void {
        if (this.busy()) return;
        this.clearSecretValues();
        this.dialogRef.close(this.pluginToRetry() ?? undefined);
    }

    /** Only the slots with a value: the others keep their current secret. */
    private enteredSecrets(): PluginSecretValues {
        return Object.fromEntries(Object.entries(this.form.getRawValue()).filter(([, value]) => value !== ''));
    }

    /** Drops the entered values from the form, its inputs included. */
    private clearSecretValues(): void {
        this.form.reset();
    }

    private trackFormStatus(): void {
        this.formStatus.set(this.form.status);
        this.form.statusChanges
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe((status) => this.formStatus.set(status));
    }

    /** Backdrop click and Escape go through close(), so they are ignored while a request is on its way. */
    private routeDismissThroughClose(): void {
        this.dialogRef.disableClose = true;
        merge(
            this.dialogRef.backdropClick,
            this.dialogRef.keydownEvents.pipe(
                filter((event) => event.key === 'Escape' && !hasModifierKey(event)),
                tap((event) => event.preventDefault())
            )
        )
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe(() => this.close());
    }
}

/** One optional control per slot; the form is valid once at least one slot has an acceptable value. */
function buildSecretsForm(slots: PluginSecretSlot[]): SecretsForm {
    const controls: Record<string, FormControl<string>> = {};
    for (const slot of slots) {
        controls[slot.name] = new FormControl('', { nonNullable: true, validators: pluginSecretValueValidators() });
    }
    return new FormGroup(controls, { validators: requireAnySecretValue });
}

/** The server refuses an empty `secrets` object. */
function requireAnySecretValue(group: AbstractControl<PluginSecretValues>): ValidationErrors | null {
    return Object.values(group.value).some((value) => value !== '') ? null : { noSecretValue: true };
}
