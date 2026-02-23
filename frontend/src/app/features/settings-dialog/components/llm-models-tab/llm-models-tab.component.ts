import {
    ChangeDetectionStrategy,
    Component,
    OnInit,
    signal,
    inject,
} from '@angular/core';
import { CommonModule } from '@angular/common';
import { Dialog } from '@angular/cdk/dialog';
import { AppIconComponent } from '../../../../shared/components/app-icon/app-icon.component';

import { LoadingState } from '../../../../core/enums/loading-state.enum';
import { LlmConfigItemComponent } from './llm-config-item/llm-config-item.component';
import { ButtonComponent } from '../../../../shared/components/buttons/button/button.component';
import { AddLlmConfigDialogComponent, AddLlmConfigDialogData } from './add-llm-config-dialog/add-llm-config-dialog.component';
import {
    FullLLMConfigService,
    FullLLMConfig,
} from '../../services/llms/full-llm-config.service';
import { LLM_Config_Service } from '../../services/llms/LLM_config.service';
import { UpdateLLMConfigRequest } from '../../models/llms/LLM_config.model';

@Component({
    selector: 'app-llm-models-tab',
    standalone: true,
    imports: [CommonModule, LlmConfigItemComponent, ButtonComponent],
    templateUrl: './llm-models-tab.component.html',
    styleUrls: ['./llm-models-tab.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class LlmModelsTabComponent implements OnInit {
    private readonly fullLlmConfigService = inject(FullLLMConfigService);
    private readonly dialog = inject(Dialog);
    private readonly llmConfigService = inject(LLM_Config_Service);

    public llmConfigs = signal<FullLLMConfig[]>([]);
    public status = signal<LoadingState>(LoadingState.IDLE);
    public errorMessage = signal<string | null>(null);

    constructor() {}

    public ngOnInit(): void {
        this.loadConfigs();
    }

    public refreshData(): void {
        this.status.set(LoadingState.LOADING);
        this.loadConfigs();
    }

    public createNewConfig(): void {
        const dialogRef = this.dialog.open(AddLlmConfigDialogComponent, {
            width: '500px',
            disableClose: true,
        });

        dialogRef.closed.subscribe((result) => {
            if (result === true) {
                this.refreshData();
            }
        });
    }

    private loadConfigs(): void {
        this.status.set(LoadingState.LOADING);

        this.fullLlmConfigService.getFullLLMConfigs().subscribe({
            next: (configs) => {
                const sortedConfigs = configs.sort((a, b) => b.id - a.id);
                this.llmConfigs.set(sortedConfigs);
                this.status.set(LoadingState.LOADED);
            },
            error: (err) => {
                console.error('Failed to load LLM configurations:', err);
                this.errorMessage.set(
                    'Failed to load configurations. Please try again.'
                );
                this.status.set(LoadingState.ERROR);
            },
        });
    }

    public onFavoriteToggled(event: { id: string | number; value: boolean }) {
        // Placeholder for favorite toggle logic
    }

    public onEnabledToggled(event: { id: string | number; value: boolean }) {
        const config: FullLLMConfig | undefined = this.llmConfigs().find(
            (c) => c.id === event.id
        );
        if (!config) return;
        const updateReq: UpdateLLMConfigRequest = {
            id: config.id,
            temperature: config.temperature,
            api_key: config.api_key,
            is_visible: event.value,
            model: config.model,
            custom_name: config.custom_name,
        };
        this.llmConfigService.updateConfig(updateReq).subscribe({
            next: (updated) => {
                // Update local array
                this.llmConfigs.set(
                    this.llmConfigs().map((c) =>
                        c.id === updated.id
                            ? { ...c, is_visible: updated.is_visible }
                            : c
                    )
                );
            },
            error: (err) => {
                console.error('Failed to update config:', err);
            },
        });
    }

    public onConfigureClicked(id: string | number) {
        const config = this.llmConfigs().find((c) => c.id === id);
        if (!config) return;

        const dialogData: AddLlmConfigDialogData = {
            editConfig: {
                id: config.id,
                custom_name: config.custom_name,
                model: config.model,
                api_key: config.api_key,
                temperature: config.temperature,
                top_p: config.top_p ?? null,
                stop: config.stop ?? null,
                max_tokens: config.max_tokens ?? null,
                presence_penalty: config.presence_penalty ?? null,
                frequency_penalty: config.frequency_penalty ?? null,
                logit_bias: config.logit_bias ?? null,
                response_format: config.response_format ?? null,
                seed: config.seed ?? null,
                timeout: config.timeout ?? null,
                headers: config.headers ?? undefined,
                is_visible: config.is_visible,
            },
        };

        const dialogRef = this.dialog.open(AddLlmConfigDialogComponent, {
            width: '500px',
            disableClose: true,
            data: dialogData,
        });
        dialogRef.closed.subscribe((result) => {
            if (result === true) {
                this.refreshData();
            }
        });
    }

    public onDeleteClicked(id: string | number) {
        this.llmConfigService.deleteConfig(Number(id)).subscribe({
            next: () => {
                this.llmConfigs.set(
                    this.llmConfigs().filter((c) => c.id !== id)
                );
            },
            error: (err) => {
                console.error('Failed to delete config:', err);
            },
        });
    }
}
