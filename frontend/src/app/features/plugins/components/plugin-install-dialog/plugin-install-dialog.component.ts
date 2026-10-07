import { DialogRef } from '@angular/cdk/dialog';
import { hasModifierKey } from '@angular/cdk/keycodes';
import { HttpErrorResponse } from '@angular/common/http';
import { Component, computed, DestroyRef, inject, OnInit, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { FormControl, FormControlStatus, FormGroup, ReactiveFormsModule, Validators } from '@angular/forms';
import { MatTooltip } from '@angular/material/tooltip';
import {
    AppSvgIconComponent,
    ButtonComponent,
    CheckboxComponent,
    CustomInputComponent,
    DragDropAreaComponent,
    FileUploaderComponent,
    Spinner2Component,
} from '@shared/components';
import { filter, merge, Subscription, tap } from 'rxjs';

import { FileSizePipe } from '../../../../shared/pipes/file-size.pipe';
import { PluginDetail, PluginInspectResult, PluginInspectSecretSlot } from '../../models/plugin.model';
import { PluginsApiService } from '../../services/plugins-api.service';
import { PluginsStoreService } from '../../services/plugins-store.service';
import {
    describeMissingPermission,
    describePluginAccess,
    describeReviewItem,
    groupPluginContents,
    isPluginIconUrl,
} from '../../utils/plugin-display.util';
import { PluginErrorView, toPluginErrorView } from '../../utils/plugin-error.util';
import { PLUGIN_SECRET_VALUE_MAX_LENGTH, pluginSecretValueValidators } from '../../utils/plugin-secret-value.util';
import { PluginSecretDestinationsComponent } from '../plugin-secret-destinations/plugin-secret-destinations.component';

type InstallStep = 'drop' | 'review' | 'progress' | 'done';

type SecretsForm = FormGroup<Record<string, FormControl<string>>>;

/** The server refuses larger plugin files; checked here too so nothing is uploaded in vain. */
export const PLUGIN_MAX_FILE_MEGABYTES = 30;
export const PLUGIN_MAX_FILE_BYTES = PLUGIN_MAX_FILE_MEGABYTES * 1024 * 1024;

const UI_ACKNOWLEDGEMENT =
    "This plugin runs its own code in a sandboxed page. It can use what's listed above with your permissions, and anything it can see could be sent to the plugin's author.";
const NO_UI_ACKNOWLEDGEMENT =
    'This plugin adds everything listed above to this organization, including any code it contains, and it runs with the access listed above.';

const STEPS: { id: InstallStep; label: string }[] = [
    { id: 'drop', label: 'File' },
    { id: 'review', label: 'Review' },
    { id: 'progress', label: 'Install' },
    { id: 'done', label: 'Done' },
];

@Component({
    selector: 'app-plugin-install-dialog',
    imports: [
        ReactiveFormsModule,
        AppSvgIconComponent,
        ButtonComponent,
        CheckboxComponent,
        CustomInputComponent,
        DragDropAreaComponent,
        FileUploaderComponent,
        Spinner2Component,
        MatTooltip,
        FileSizePipe,
        PluginSecretDestinationsComponent,
    ],
    templateUrl: './plugin-install-dialog.component.html',
    styleUrls: ['./plugin-install-dialog.component.scss'],
})
export class PluginInstallDialogComponent implements OnInit {
    protected readonly step = signal<InstallStep>('drop');
    protected readonly file = signal<File | null>(null);
    protected readonly inspecting = signal(false);
    protected readonly inspection = signal<PluginInspectResult | null>(null);
    /** Why the chosen file can't be reviewed (bad file, inspect error, already installed). */
    protected readonly fileError = signal<PluginErrorView | null>(null);
    /** Why the last install attempt failed; shown on the review step. */
    protected readonly installError = signal<PluginErrorView | null>(null);
    protected readonly uploadPercent = signal(0);
    protected readonly installedPlugin = signal<PluginDetail | null>(null);
    protected readonly secretsForm = signal<SecretsForm>(new FormGroup({}));
    protected readonly acknowledged = signal(false);
    private readonly secretsFormStatus = signal<FormControlStatus>('VALID');

    protected readonly title = computed(() => {
        switch (this.step()) {
            case 'drop':
                return 'Add plugin';
            case 'review':
                return 'Review plugin';
            case 'progress':
                return 'Adding plugin';
            case 'done':
                return 'Plugin added';
        }
    });
    protected readonly stepIndex = computed(() => STEPS.findIndex((step) => step.id === this.step()));
    /** Closing is blocked from the first uploaded byte until the server has answered. */
    protected readonly closeBlocked = computed(() => this.step() === 'progress');
    protected readonly isUploadComplete = computed(() => this.uploadPercent() >= 100);
    protected readonly iconUrl = computed(() => {
        const url = this.inspection()?.plugin.icon_data_url;
        return isPluginIconUrl(url) ? url : null;
    });
    protected readonly contentGroups = computed(() => groupPluginContents(this.inspection()?.contents ?? []));
    protected readonly accessLines = computed(() => (this.inspection()?.access ?? []).map(describePluginAccess));
    protected readonly codeReviewLines = computed(() =>
        (this.inspection()?.code_review_items ?? []).map(describeReviewItem)
    );
    protected readonly blockers = computed(() => {
        const inspection = this.inspection();
        if (!inspection) return [];
        const missing = inspection.missing_permissions.map(
            (permission) => `Your role can't ${describeMissingPermission(permission)}.`
        );
        return [...missing, ...inspection.conflicts.map((conflict) => conflict.message)];
    });
    protected readonly isBlocked = computed(() => {
        const inspection = this.inspection();
        return !!inspection && (!inspection.can_install || this.blockers().length > 0);
    });
    protected readonly acknowledgement = computed(() =>
        this.inspection()?.plugin.has_ui ? UI_ACKNOWLEDGEMENT : NO_UI_ACKNOWLEDGEMENT
    );
    protected readonly canInstall = computed(
        () =>
            this.step() === 'review' &&
            !!this.file() &&
            !this.isBlocked() &&
            this.acknowledged() &&
            this.secretsFormStatus() === 'VALID'
    );

    protected readonly steps = STEPS;
    protected readonly secretValueMaxLength = PLUGIN_SECRET_VALUE_MAX_LENGTH;
    protected readonly fileHint = `One .zip file, up to ${PLUGIN_MAX_FILE_MEGABYTES} MB`;

    private readonly dialogRef = inject(DialogRef<PluginDetail | undefined>);
    private readonly pluginsApiService = inject(PluginsApiService);
    private readonly pluginsStore = inject(PluginsStoreService);
    private readonly destroyRef = inject(DestroyRef);
    private inspectSubscription: Subscription | null = null;

    ngOnInit(): void {
        this.routeDismissThroughClose();
    }

    onFilesChosen(files: FileList): void {
        const chosen = Array.from(files);
        const problem = describeFileProblem(chosen);
        if (problem) {
            this.resetToDrop();
            this.fileError.set({ code: null, message: problem, details: [] });
            return;
        }
        this.inspect(chosen[0]);
    }

    onFilesRejected(): void {
        this.resetToDrop();
        this.fileError.set({ code: null, message: 'A plugin is a single .zip file.', details: [] });
    }

    chooseAnotherFile(): void {
        this.resetToDrop();
    }

    install(): void {
        const file = this.file();
        if (!file || !this.canInstall()) return;

        this.installError.set(null);
        this.uploadPercent.set(0);
        this.step.set('progress');

        this.pluginsStore
            .install(file, this.secretsForm().getRawValue())
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe({
                next: (event) => {
                    if (event.kind === 'progress') {
                        this.uploadPercent.set(event.percent);
                        return;
                    }
                    this.installedPlugin.set(event.plugin);
                    this.step.set('done');
                },
                error: (error: HttpErrorResponse) => {
                    this.installError.set(toPluginErrorView(error, 'The plugin could not be added.'));
                    this.step.set('review');
                },
                // A response without a plugin must not leave the dialog stuck with close blocked.
                complete: () => {
                    if (this.step() !== 'progress') return;
                    this.installError.set({
                        code: null,
                        message: "The server didn't confirm the install. Check the plugin list before trying again.",
                        details: [],
                    });
                    this.step.set('review');
                },
            });
    }

    close(): void {
        if (this.closeBlocked()) return;
        this.dialogRef.close(this.installedPlugin() ?? undefined);
    }

    private inspect(file: File): void {
        this.resetToDrop();
        this.file.set(file);
        this.inspecting.set(true);

        this.inspectSubscription = this.pluginsApiService
            .inspect(file)
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe({
                next: (inspection) => {
                    this.inspecting.set(false);
                    this.inspection.set(inspection);
                    this.buildSecretsForm(inspection.secret_slots);
                    this.step.set('review');
                },
                error: (error: HttpErrorResponse) => {
                    this.inspecting.set(false);
                    this.fileError.set(toPluginErrorView(error, "The plugin file couldn't be checked."));
                },
            });
    }

    private resetToDrop(): void {
        this.inspectSubscription?.unsubscribe();
        this.inspectSubscription = null;
        this.step.set('drop');
        this.file.set(null);
        this.inspecting.set(false);
        this.inspection.set(null);
        this.fileError.set(null);
        this.installError.set(null);
        this.acknowledged.set(false);
        this.buildSecretsForm([]);
    }

    private buildSecretsForm(slots: PluginInspectSecretSlot[]): void {
        const controls: Record<string, FormControl<string>> = {};
        for (const slot of slots) {
            controls[slot.name] = new FormControl('', {
                nonNullable: true,
                validators: [Validators.required, ...pluginSecretValueValidators()],
            });
        }
        const form: SecretsForm = new FormGroup(controls);
        this.secretsForm.set(form);
        this.secretsFormStatus.set(form.status);
        form.statusChanges
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe((status) => this.secretsFormStatus.set(status));
    }

    /** Backdrop click and Escape go through close(), so they are ignored while installing. */
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

function describeFileProblem(files: File[]): string | null {
    if (files.length !== 1) return 'Add one plugin file at a time.';
    const [file] = files;
    if (!file.name.toLowerCase().endsWith('.zip')) return 'A plugin is a single .zip file.';
    if (file.size === 0) return 'The file is empty.';
    if (file.size > PLUGIN_MAX_FILE_BYTES) return `The plugin file is larger than ${PLUGIN_MAX_FILE_MEGABYTES} MB.`;
    return null;
}
