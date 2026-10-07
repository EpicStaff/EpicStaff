import { DIALOG_DATA, DialogRef } from '@angular/cdk/dialog';
import { hasModifierKey } from '@angular/cdk/keycodes';
import { HttpErrorResponse } from '@angular/common/http';
import { Component, computed, DestroyRef, inject, OnInit, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import {
    AbstractControl,
    FormControl,
    FormControlStatus,
    ReactiveFormsModule,
    ValidationErrors,
    Validators,
} from '@angular/forms';
import { MatTooltip } from '@angular/material/tooltip';
import { AppSvgIconComponent, ButtonComponent, CustomInputComponent } from '@shared/components';
import { filter, merge, Observable, tap } from 'rxjs';

import { ToastService } from '../../../../services/notifications';
import { PluginDetail, PluginSummary } from '../../models/plugin.model';
import { PluginsStoreService } from '../../services/plugins-store.service';
import { PluginErrorView, toPluginErrorView } from '../../utils/plugin-error.util';
import { PLUGIN_DEV_URL_MAX_LENGTH, toPluginDevFrameUrl } from '../../utils/plugin-frame-url.util';

export interface PluginDevModeDialogData {
    plugin: PluginSummary;
}

const DEFAULT_DEV_URL = 'http://localhost:4300/';

/**
 * Sets or clears the dev URL of a plugin's page: while set, the admin who set it (only them) gets
 * the page from their own dev server, with live reload, real data and the real bridge. Offered
 * only while the instance runs in plugin dev mode.
 */
@Component({
    selector: 'app-plugin-dev-mode-dialog',
    imports: [ReactiveFormsModule, AppSvgIconComponent, ButtonComponent, CustomInputComponent, MatTooltip],
    templateUrl: './plugin-dev-mode-dialog.component.html',
    styleUrls: ['./plugin-dev-mode-dialog.component.scss'],
})
export class PluginDevModeDialogComponent implements OnInit {
    protected readonly saving = signal(false);
    protected readonly error = signal<PluginErrorView | null>(null);
    private readonly urlStatus = signal<FormControlStatus>('INVALID');

    protected readonly canSave = computed(() => this.urlStatus() === 'VALID' && !this.saving());
    protected readonly urlError = computed(() =>
        this.urlStatus() === 'INVALID'
            ? 'Use http://localhost or http://127.0.0.1, with an optional port and path.'
            : ''
    );

    protected readonly data: PluginDevModeDialogData = inject(DIALOG_DATA);
    protected readonly urlControl = new FormControl(this.data.plugin.dev_ui_url ?? DEFAULT_DEV_URL, {
        nonNullable: true,
        validators: [Validators.required, devUrlValidator],
    });
    protected readonly maxLength = PLUGIN_DEV_URL_MAX_LENGTH;
    /** Bound as a property, so only the inner `<input>` carries the id (not the component's host too). */
    protected readonly urlInputId = 'plugin-dev-ui-url';

    private readonly dialogRef = inject(DialogRef<PluginDetail | undefined>);
    private readonly pluginsStore = inject(PluginsStoreService);
    private readonly toastService = inject(ToastService);
    private readonly destroyRef = inject(DestroyRef);

    ngOnInit(): void {
        this.routeDismissThroughClose();
        this.urlStatus.set(this.urlControl.status);
        this.urlControl.statusChanges
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe((status) => this.urlStatus.set(status));
    }

    save(): void {
        if (!this.canSave()) return;
        const url = this.urlControl.value.trim();
        this.run(
            this.pluginsStore.setDevUi(this.data.plugin.id, url),
            `${this.data.plugin.name} loads from ${url} for you`
        );
    }

    turnOff(): void {
        if (this.saving()) return;
        this.run(this.pluginsStore.clearDevUi(this.data.plugin.id), `Dev mode off for ${this.data.plugin.name}`);
    }

    close(): void {
        if (this.saving()) return;
        this.dialogRef.close(undefined);
    }

    private run(request: Observable<PluginDetail>, successMessage: string): void {
        this.saving.set(true);
        this.error.set(null);
        request.pipe(takeUntilDestroyed(this.destroyRef)).subscribe({
            next: (plugin) => {
                this.saving.set(false);
                this.toastService.success(successMessage);
                this.dialogRef.close(plugin);
            },
            error: (error: HttpErrorResponse) => {
                this.saving.set(false);
                this.error.set(toPluginErrorView(error, "Dev mode couldn't be changed."));
            },
        });
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

/** The server's rule, checked here first: plain `http` on `localhost` / `127.0.0.1`, no query or fragment. */
function devUrlValidator(control: AbstractControl<string>): ValidationErrors | null {
    const value = control.value?.trim() ?? '';
    if (value === '') return null;
    return toPluginDevFrameUrl(value) ? null : { devUrl: true };
}
