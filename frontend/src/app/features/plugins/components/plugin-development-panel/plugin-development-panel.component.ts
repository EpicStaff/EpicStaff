import { DatePipe } from '@angular/common';
import { Component, computed, DestroyRef, inject, input, output, signal } from '@angular/core';
import { takeUntilDestroyed, toObservable } from '@angular/core/rxjs-interop';
import {
    ButtonComponent,
    ConfirmationDialogService,
    CopyFieldComponent,
    FetchErrorStateComponent,
    InputNumberComponent,
    LoadingSpinnerComponent,
} from '@shared/components';
import { downloadBlob, escapeHtml } from '@shared/utils';
import { catchError, filter, finalize, Observable, of, switchMap, tap } from 'rxjs';

import { ToastService } from '../../../../services/notifications';
import { PluginDevelopment, PluginDevelopmentUpdate } from '../../models/plugin-development.model';
import { PluginErrorItem, PluginErrorView } from '../../models/plugin-error.model';
import { PluginsAdminStorageService } from '../../services/plugins-admin-storage.service';
import { attachmentFileName } from '../../utils/plugin-attachment.util';
import { toPluginErrorView } from '../../utils/plugin-error-message.util';

/** The lowest port a development target may use, as the server checks it. */
export const PLUGIN_DEVELOPMENT_PORT_MIN = 1024;

/** The highest port a development target may use. */
export const PLUGIN_DEVELOPMENT_PORT_MAX = 65535;

/** The port `epicstaff-plugin dev` listens on unless told otherwise. */
export const PLUGIN_DEVELOPMENT_BACKEND_DEFAULT_PORT = 8001;

/** Said when `host.docker.internal` does not resolve inside EpicStaff. */
export const PLUGIN_DEVELOPMENT_HOST_UNRESOLVED =
    'host.docker.internal does not resolve in django_app: start EpicStaff with docker-compose.plugins-dev.yaml';

type PortKey = keyof PluginDevelopmentUpdate;

/** What the panel is sending; the buttons wait meanwhile. */
type DevelopmentAction = 'save' | 'stop' | 'download';

const PORT_LABELS: Readonly<Record<PortKey, string>> = {
    backend_port: 'Backend port',
    spa_port: 'Frontend dev server port',
};

const PORT_PROBLEM = `Enter a whole number from ${PLUGIN_DEVELOPMENT_PORT_MIN} to ${PLUGIN_DEVELOPMENT_PORT_MAX}.`;

interface PortField {
    key: PortKey;
    label: string;
    /** What the input holds now: the draft once touched, else the stored port. */
    value: number | null;
    /** The message the input shows: the server's from the last refused save, else why the value cannot be saved. */
    message: string;
    /** The value cannot be saved as it is. */
    invalid: boolean;
}

/**
 * A plugin's Development tab, while development mode is on: where EpicStaff routes the plugin on the author's machine
 * (`host.docker.internal` and the address it resolves to, the API address a development backend calls), the ports the
 * current package can use (Backend port with a backend, Frontend dev server port with a page), Stop development, and,
 * for a plugin with a backend, the development runtime file and the command that runs the backend with it.
 *
 * Every choice follows the server: which ports are offered, whether the mode is on, when the file was issued. Save
 * sends both ports; Stop development and the download ask for confirmation first. The downloaded file is handed to the
 * browser as the server sent it: the panel never reads, keeps or logs it.
 */
@Component({
    selector: 'app-plugin-development-panel',
    imports: [
        ButtonComponent,
        CopyFieldComponent,
        DatePipe,
        FetchErrorStateComponent,
        InputNumberComponent,
        LoadingSpinnerComponent,
    ],
    templateUrl: './plugin-development-panel.component.html',
    styleUrl: './plugin-development-panel.component.scss',
})
export class PluginDevelopmentPanelComponent {
    readonly identifier = input.required<string>();
    readonly pluginName = input.required<string>();
    /** The target was stored or removed: the plugin's summary may have changed (its badge, the Runtime tab's line). */
    readonly changed = output<void>();

    protected readonly development = signal<PluginDevelopment | null>(null);
    protected readonly isLoading = signal(true);
    protected readonly loadError = signal<PluginErrorView | null>(null);
    protected readonly busyAction = signal<DevelopmentAction | null>(null);
    protected readonly saveError = signal<PluginErrorView | null>(null);
    /** The server's message per port, from the last refused save. */
    protected readonly fieldErrors = signal<Readonly<Partial<Record<PortKey, string>>>>({});
    /** Port inputs the SuperAdmin touched; `null` = no port. */
    protected readonly drafts = signal<Readonly<Partial<Record<PortKey, number | null>>>>({});
    protected readonly isBusy = computed(() => this.busyAction() !== null);
    /** The ports the current package can use, in display order. */
    protected readonly fields = computed<PortField[]>(() => {
        const development = this.development();
        if (!development?.development_mode) return [];
        const keys: PortKey[] = [
            ...(development.can_use_backend ? (['backend_port'] as const) : []),
            ...(development.can_use_spa ? (['spa_port'] as const) : []),
        ];
        const drafts = this.drafts();
        const fieldErrors = this.fieldErrors();
        return keys.map((key) => {
            const value = key in drafts ? (drafts[key] ?? null) : (development.target?.[key] ?? null);
            const problem = portProblem(value);
            return {
                key,
                label: PORT_LABELS[key],
                value,
                message: fieldErrors[key] ?? problem ?? '',
                invalid: fieldErrors[key] !== undefined || problem !== null,
            };
        });
    });
    /** Every port offered is empty: there is nothing to save (removing a stored target is Stop development's job). */
    protected readonly bothEmpty = computed(() => {
        const fields = this.fields();
        return fields.length > 0 && fields.every((field) => field.value === null);
    });
    protected readonly canSave = computed(() => {
        const development = this.development();
        if (!development || this.isBusy() || this.bothEmpty()) return false;
        const fields = this.fields();
        const changed = fields.some((field) => field.value !== (development.target?.[field.key] ?? null));
        return changed && fields.every((field) => portProblem(field.value) === null);
    });
    /** Something is routed or keys are in use: Stop development has something to stop. */
    protected readonly canStop = computed(() => {
        const development = this.development();
        return development !== null && (development.target !== null || development.runtime_file_issued_at !== null);
    });
    /** A backend port is stored, but no development keys are: the backend cannot verify requests or call EpicStaff. */
    protected readonly needsRuntimeFile = computed(() => {
        const development = this.development();
        return (
            development?.development_mode === true &&
            development.can_use_backend &&
            development.target?.backend_port != null &&
            development.runtime_file_issued_at === null
        );
    });
    /** The current package has neither a backend nor a page, so there is nothing to route. */
    protected readonly nothingToRoute = computed(() => {
        const development = this.development();
        return development?.development_mode === true && !development.can_use_backend && !development.can_use_spa;
    });
    protected readonly command = computed(() => {
        const port = this.development()?.target?.backend_port ?? PLUGIN_DEVELOPMENT_BACKEND_DEFAULT_PORT;
        return `epicstaff-plugin dev <your plugin directory> --runtime-file <downloaded file> --port ${port}`;
    });
    /** Problems of a refused save that belong to no port. */
    protected readonly otherErrorItems = computed<PluginErrorItem[]>(
        () => this.saveError()?.items.filter((item) => !isPortKey(item.loc)) ?? []
    );
    private readonly reloads = signal(0);
    private readonly request = computed(() => ({ identifier: this.identifier(), reload: this.reloads() }));

    protected readonly hostUnresolved = PLUGIN_DEVELOPMENT_HOST_UNRESOLVED;
    protected readonly portMin = PLUGIN_DEVELOPMENT_PORT_MIN;
    protected readonly portMax = PLUGIN_DEVELOPMENT_PORT_MAX;

    private readonly storage = inject(PluginsAdminStorageService);
    private readonly confirmation = inject(ConfirmationDialogService);
    private readonly toast = inject(ToastService);
    private readonly destroyRef = inject(DestroyRef);

    constructor() {
        toObservable(this.request)
            .pipe(
                tap(() => this.loadError.set(null)),
                switchMap(({ identifier }) =>
                    this.storage.getDevelopment(identifier).pipe(
                        catchError((error: unknown) => {
                            this.loadError.set(toPluginErrorView(error, "Couldn't load the development state."));
                            return of(null);
                        }),
                        finalize(() => this.isLoading.set(false))
                    )
                ),
                takeUntilDestroyed()
            )
            .subscribe((development) => {
                if (development) this.show(development);
            });
    }

    protected reload(): void {
        this.reloads.update((count) => count + 1);
    }

    protected setDraft(key: PortKey, value: number | null): void {
        this.drafts.update((drafts) => ({ ...drafts, [key]: value }));
    }

    protected save(): void {
        const development = this.development();
        if (!development || !this.canSave()) return;
        const values = new Map(this.fields().map((field) => [field.key, field.value]));
        // A port the package cannot use is not offered, so it is not routed.
        const update: PluginDevelopmentUpdate = {
            backend_port: values.get('backend_port') ?? null,
            spa_port: values.get('spa_port') ?? null,
        };
        this.saveError.set(null);
        this.fieldErrors.set({});
        this.run('save', this.storage.updateDevelopment(this.identifier(), update)).subscribe({
            next: (saved) => {
                this.show(saved);
                this.toast.success('Development target saved. Requests follow it within about 10 seconds.');
                this.changed.emit();
            },
            error: (error: unknown) => {
                const view = toPluginErrorView(error, "Couldn't save the development target.");
                this.fieldErrors.set(fieldErrorsOf(view.items));
                this.saveError.set(view);
            },
        });
    }

    protected stop(): void {
        if (this.isBusy()) return;
        const identifier = this.identifier();
        const name = this.pluginName();
        this.confirm(
            'Stop development?',
            `${name} is served from its installed package again, and the development keys stop working.`,
            'Stop development'
        )
            .pipe(switchMap(() => this.run('stop', this.storage.clearDevelopment(identifier))))
            .subscribe({
                next: () => {
                    this.toast.success(`Development of ${name} stopped.`);
                    this.reload();
                    this.changed.emit();
                },
                error: (error: unknown) => {
                    this.toast.error(toPluginErrorView(error, "Couldn't stop development.").message);
                    this.reload();
                },
            });
    }

    protected download(): void {
        if (this.isBusy()) return;
        const identifier = this.identifier();
        const name = this.pluginName();
        this.confirm(
            'Download the development runtime file?',
            `This file holds keys that act for ${name} in every organization it is granted to, and the plugin's ` +
                "secret settings. Keep it outside your plugin's source. Downloading again stops the previous file's keys.",
            'Download'
        )
            .pipe(switchMap(() => this.run('download', this.storage.downloadDevelopmentRuntimeFile(identifier))))
            .subscribe({
                next: (response) => {
                    const fileName =
                        attachmentFileName(response.headers.get('Content-Disposition')) ??
                        `${identifier}-development-runtime.json`;
                    if (response.body) {
                        // Handed to the browser as it came; never read, kept or logged.
                        downloadBlob(response.body, fileName);
                        this.toast.success(`Downloaded ${fileName}. Keep it outside your plugin's source.`);
                    } else {
                        this.toast.error("Couldn't download the development runtime file: the server sent no file.");
                    }
                    this.reload();
                },
                error: (error: unknown) => {
                    this.toast.error(
                        toPluginErrorView(error, "Couldn't download the development runtime file.").message
                    );
                    this.reload();
                },
            });
    }

    private confirm(title: string, message: string, confirmText: string): Observable<true> {
        return this.confirmation
            .confirm({ title, message: escapeHtml(message), type: 'warning', confirmText, cancelText: 'Cancel' })
            .pipe(
                filter((answer): answer is true => answer === true),
                takeUntilDestroyed(this.destroyRef)
            );
    }

    /** Sends `request` with the buttons waiting until it settles. */
    private run<Result>(action: DevelopmentAction, request: Observable<Result>): Observable<Result> {
        this.busyAction.set(action);
        return request.pipe(
            finalize(() => this.busyAction.set(null)),
            takeUntilDestroyed(this.destroyRef)
        );
    }

    private show(development: PluginDevelopment): void {
        this.development.set(development);
        this.drafts.set({});
        this.fieldErrors.set({});
    }
}

function portProblem(value: number | null): string | null {
    if (value === null) return null;
    if (!Number.isInteger(value) || value < PLUGIN_DEVELOPMENT_PORT_MIN || value > PLUGIN_DEVELOPMENT_PORT_MAX) {
        return PORT_PROBLEM;
    }
    return null;
}

function isPortKey(loc: string): loc is PortKey {
    return Object.hasOwn(PORT_LABELS, loc);
}

function fieldErrorsOf(items: PluginErrorItem[]): Partial<Record<PortKey, string>> {
    const errors: Partial<Record<PortKey, string>> = {};
    for (const item of items) {
        if (!isPortKey(item.loc)) continue;
        const known = errors[item.loc];
        errors[item.loc] = known ? `${known} ${item.message}` : item.message;
    }
    return errors;
}
