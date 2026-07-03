import { DIALOG_DATA, DialogRef } from '@angular/cdk/dialog';
import { ChangeDetectionStrategy, Component, DestroyRef, inject, OnInit, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { FormBuilder, FormGroup, ReactiveFormsModule, Validators } from '@angular/forms';
import { IconButtonComponent, TabButtonComponent } from '@shared/components';
import { FullLLMConfig, FullLLMConfigService } from '@shared/services';

import {
    AdvancedTabComponent,
    ExecutionTabComponent,
    GeneralTabComponent,
    Tab,
    TabId,
} from '../../../../../../../shared/components/create-agent-form-dialog/tabs';

export interface AgentAdditionalSettingsData {
    fcm_llm_config: number | null;
    max_iter: number | null;
    max_rpm: number | null;
    max_execution_time: number | null;
    max_retry_limit: number | null;
    cache: boolean | null;
}

export interface AgentAdditionalSettingsResult {
    fcm_llm_config: number | null;
    max_iter: number;
    max_rpm: number;
    max_execution_time: number;
    max_retry_limit: number;
    cache: boolean;
}

@Component({
    selector: 'app-agent-additional-settings-dialog',
    imports: [
        ReactiveFormsModule,
        IconButtonComponent,
        TabButtonComponent,
        GeneralTabComponent,
        ExecutionTabComponent,
        AdvancedTabComponent,
    ],
    templateUrl: './agent-additional-settings-dialog.component.html',
    styleUrls: ['./agent-additional-settings-dialog.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class AgentAdditionalSettingsDialogComponent implements OnInit {
    private readonly fb = inject(FormBuilder);
    private readonly destroyRef = inject(DestroyRef);
    private readonly fullLlmConfigService = inject(FullLLMConfigService);
    private readonly data = inject<AgentAdditionalSettingsData>(DIALOG_DATA);

    readonly dialogRef = inject<DialogRef<AgentAdditionalSettingsResult | undefined>>(DialogRef);

    readonly activeTab = signal<TabId>(TabId.GENERAL);
    readonly loadingLLMs = signal<boolean>(true);
    readonly combinedLLMs = signal<FullLLMConfig[]>([]);

    readonly tabs: Tab[] = [
        { id: TabId.GENERAL, label: 'General' },
        { id: TabId.EXECUTION, label: 'Execution' },
        { id: TabId.ADVANCED, label: 'Advanced' },
    ];

    readonly form: FormGroup = this.fb.group({
        fcm_llm_config: [this.data.fcm_llm_config],
        max_iter: [this.data.max_iter ?? 10, [Validators.min(1), Validators.max(30)]],
        max_rpm: [this.data.max_rpm ?? 10, [Validators.min(1), Validators.max(30)]],
        max_execution_time: [this.data.max_execution_time ?? 60, [Validators.min(1), Validators.max(600)]],
        max_retry_limit: [this.data.max_retry_limit ?? 3, [Validators.min(1), Validators.max(10)]],
        cache: [this.data.cache ?? false],
    });

    ngOnInit(): void {
        this.fullLlmConfigService
            .getFullLLMConfigs()
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe({
                next: (configs) => {
                    this.combinedLLMs.set(configs);
                    this.loadingLLMs.set(false);
                },
                error: () => this.loadingLLMs.set(false),
            });
    }

    save(): void {
        if (this.form.invalid) return;
        this.dialogRef.close(this.form.getRawValue() as AgentAdditionalSettingsResult);
    }

    protected readonly TabId = TabId;
}
