import { Component, computed, DestroyRef, inject, input, output, signal } from '@angular/core';
import { takeUntilDestroyed, toObservable } from '@angular/core/rxjs-interop';
import {
    ButtonComponent,
    CheckboxComponent,
    FetchErrorStateComponent,
    InputNumberComponent,
    LoadingSpinnerComponent,
} from '@shared/components';
import { catchError, finalize, of, switchMap, tap } from 'rxjs';

import { ToastService } from '../../../../services/notifications';
import {
    PluginLimitKey,
    PluginLimitsResponse,
    PluginLimitsUpdate,
    PluginNumericLimitKey,
} from '../../models/plugin-backend.model';
import { PluginErrorItem, PluginErrorView } from '../../models/plugin-error.model';
import { PluginsAdminStorageService } from '../../services/plugins-admin-storage.service';
import { PLUGIN_CPU_PRIORITY_LABELS, PLUGIN_LIMIT_LABELS } from '../../utils/plugin-display.util';
import { toPluginErrorView } from '../../utils/plugin-error-message.util';
import { PluginBadgeComponent } from '../plugin-badge/plugin-badge.component';

/** The numeric limits, in display order. */
const NUMERIC_LIMIT_KEYS: readonly PluginNumericLimitKey[] = [
    'memory_mb',
    'db_connections',
    'statement_timeout_seconds',
    'requests_per_minute',
];

const LIMIT_UNITS: Readonly<Record<PluginNumericLimitKey, string>> = {
    memory_mb: 'MB',
    db_connections: '',
    statement_timeout_seconds: 's',
    requests_per_minute: '/ min',
};

/** `overrides.<key>` in an `errors[]` item's `loc`. */
const LIMIT_LOC_PREFIX = 'overrides.';

interface NumericLimitRow {
    key: PluginNumericLimitKey;
    label: string;
    requested: string;
    platformMax: string;
    effective: string;
    /** The highest override allowed: `min(requested, platform max)`. */
    bound: number;
    enforced: boolean;
    /** An override is stored for this limit. */
    hasOverride: boolean;
    /** What the override input holds now. */
    draft: number | null;
    /** Why the draft cannot be saved, or `null`. */
    problem: string | null;
}

/**
 * A backend plugin's limits: for each, what the plugin asks for, the platform maximum, the override a SuperAdmin set
 * (only ever lower) and the effective value. Limits this version does not enforce yet are shown disabled. A save sends
 * only the changed overrides; Reset removes one (`null`). The plugin restarts with the new limits.
 */
@Component({
    selector: 'app-plugin-limits-form',
    imports: [
        ButtonComponent,
        CheckboxComponent,
        FetchErrorStateComponent,
        InputNumberComponent,
        LoadingSpinnerComponent,
        PluginBadgeComponent,
    ],
    templateUrl: './plugin-limits-form.component.html',
    styleUrl: './plugin-limits-form.component.scss',
})
export class PluginLimitsFormComponent {
    readonly identifier = input.required<string>();
    /** After a save; the plugin restarts with the new limits. */
    readonly saved = output<PluginLimitsResponse>();

    protected readonly response = signal<PluginLimitsResponse | null>(null);
    protected readonly isLoading = signal(true);
    protected readonly loadError = signal<PluginErrorView | null>(null);
    protected readonly isSaving = signal(false);
    protected readonly saveError = signal<PluginErrorView | null>(null);
    /** The server's message per limit key, from the last refused save. */
    protected readonly fieldErrors = signal<Readonly<Partial<Record<PluginLimitKey, string>>>>({});
    /** Override inputs the SuperAdmin touched; `null` = no override. */
    protected readonly drafts = signal<Readonly<Partial<Record<PluginNumericLimitKey, number | null>>>>({});
    /** The CPU override checkbox, once touched. */
    protected readonly lowCpuDraft = signal<boolean | null>(null);
    protected readonly rows = computed<NumericLimitRow[]>(() => {
        const response = this.response();
        if (!response) return [];
        const drafts = this.drafts();
        return NUMERIC_LIMIT_KEYS.map((key) => {
            const bound = Math.min(response.requested[key], response.platform_max[key]);
            const stored = response.overrides[key] ?? null;
            const draft = key in drafts ? (drafts[key] ?? null) : stored;
            return {
                key,
                label: PLUGIN_LIMIT_LABELS[key],
                requested: formatLimit(key, response.requested[key]),
                platformMax: formatLimit(key, response.platform_max[key]),
                effective: formatLimit(key, response.effective[key]),
                bound,
                enforced: response.enforced[key],
                hasOverride: stored !== null,
                draft,
                problem: overrideProblem(draft, bound),
            };
        });
    });
    protected readonly cpu = computed(() => {
        const response = this.response();
        if (!response) return null;
        const storedLow = response.overrides.cpu_priority === 'low';
        return {
            requested: PLUGIN_CPU_PRIORITY_LABELS[response.requested.cpu_priority],
            effective: PLUGIN_CPU_PRIORITY_LABELS[response.effective.cpu_priority],
            enforced: response.enforced.cpu_priority,
            /** The plugin asks for low priority itself: an override would change nothing. */
            requestsLow: response.requested.cpu_priority === 'low',
            storedLow,
            low: this.lowCpuDraft() ?? storedLow,
        };
    });
    /** What a save would send: the changed overrides only. */
    protected readonly changes = computed<PluginLimitsUpdate['overrides']>(() => {
        const response = this.response();
        const overrides: PluginLimitsUpdate['overrides'] = {};
        if (!response) return overrides;
        for (const row of this.rows()) {
            if (!row.enforced) continue;
            if (row.draft !== (response.overrides[row.key] ?? null)) overrides[row.key] = row.draft;
        }
        const cpu = this.cpu();
        if (cpu && cpu.enforced && cpu.low !== cpu.storedLow) overrides.cpu_priority = cpu.low ? 'low' : null;
        return overrides;
    });
    protected readonly canSave = computed(
        () =>
            !this.isSaving() &&
            Object.keys(this.changes()).length > 0 &&
            this.rows().every((row) => !row.enforced || row.problem === null)
    );
    /** Problems of a refused save that belong to no limit. */
    protected readonly otherErrorItems = computed<PluginErrorItem[]>(
        () => this.saveError()?.items.filter((item) => !item.loc.startsWith(LIMIT_LOC_PREFIX)) ?? []
    );
    private readonly reloads = signal(0);
    private readonly request = computed(() => ({ identifier: this.identifier(), reload: this.reloads() }));

    protected readonly cpuLabel = PLUGIN_LIMIT_LABELS.cpu_priority;

    private readonly storage = inject(PluginsAdminStorageService);
    private readonly toast = inject(ToastService);
    private readonly destroyRef = inject(DestroyRef);

    constructor() {
        toObservable(this.request)
            .pipe(
                tap(() => {
                    this.isLoading.set(true);
                    this.loadError.set(null);
                }),
                switchMap(({ identifier }) =>
                    this.storage.getLimits(identifier).pipe(
                        catchError((error: unknown) => {
                            this.loadError.set(toPluginErrorView(error, "Couldn't load the limits."));
                            return of(null);
                        }),
                        finalize(() => this.isLoading.set(false))
                    )
                ),
                takeUntilDestroyed()
            )
            .subscribe((response) => {
                if (response) this.show(response);
            });
    }

    protected reload(): void {
        this.reloads.update((count) => count + 1);
    }

    protected setDraft(key: PluginNumericLimitKey, value: number | null): void {
        this.drafts.update((drafts) => ({ ...drafts, [key]: value }));
    }

    /** Removes the override on save: the limit goes back to `min(requested, platform max)`. */
    protected reset(key: PluginNumericLimitKey): void {
        this.setDraft(key, null);
    }

    protected setLowCpu(low: boolean): void {
        this.lowCpuDraft.set(low);
    }

    protected fieldError(key: PluginLimitKey): string | null {
        return this.fieldErrors()[key] ?? null;
    }

    /** The message the override input shows (and points at): the server's, else why the draft cannot be saved. */
    protected rowError(row: NumericLimitRow): string {
        return this.fieldError(row.key) ?? row.problem ?? '';
    }

    protected save(): void {
        if (!this.canSave()) return;
        this.isSaving.set(true);
        this.saveError.set(null);
        this.fieldErrors.set({});
        this.storage
            .updateLimits(this.identifier(), { overrides: this.changes() })
            .pipe(
                finalize(() => this.isSaving.set(false)),
                takeUntilDestroyed(this.destroyRef)
            )
            .subscribe({
                next: (response) => {
                    this.show(response);
                    this.toast.success('Limits saved. The plugin restarts with them.');
                    this.saved.emit(response);
                },
                error: (error: unknown) => {
                    const view = toPluginErrorView(error, "Couldn't save the limits.");
                    this.fieldErrors.set(fieldErrorsOf(view.items));
                    this.saveError.set(view);
                },
            });
    }

    private show(response: PluginLimitsResponse): void {
        this.response.set(response);
        this.drafts.set({});
        this.lowCpuDraft.set(null);
        this.fieldErrors.set({});
    }
}

function formatLimit(key: PluginNumericLimitKey, value: number): string {
    const unit = LIMIT_UNITS[key];
    return unit ? `${value} ${unit}` : String(value);
}

function overrideProblem(draft: number | null, bound: number): string | null {
    if (draft === null) return null;
    if (!Number.isInteger(draft) || draft < 1 || draft > bound) return `Enter a whole number from 1 to ${bound}.`;
    return null;
}

function fieldErrorsOf(items: PluginErrorItem[]): Partial<Record<PluginLimitKey, string>> {
    const errors: Partial<Record<PluginLimitKey, string>> = {};
    for (const item of items) {
        if (!item.loc.startsWith(LIMIT_LOC_PREFIX)) continue;
        const key = item.loc.slice(LIMIT_LOC_PREFIX.length);
        if (isLimitKey(key)) errors[key] = errors[key] ? `${errors[key]} ${item.message}` : item.message;
    }
    return errors;
}

function isLimitKey(key: string): key is PluginLimitKey {
    return Object.hasOwn(PLUGIN_LIMIT_LABELS, key);
}
