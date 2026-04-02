import { CommonModule } from '@angular/common';
import {
    ChangeDetectionStrategy,
    ChangeDetectorRef,
    Component,
    EventEmitter,
    Input,
    OnChanges,
    OnInit,
    Output,
    signal,
    SimpleChanges,
} from '@angular/core';
import { FormsModule } from '@angular/forms';

import { GetProjectRequest } from '../../features/projects/models/project.model';
import { GetEmbeddingConfigRequest } from '../../features/settings-dialog/models/embeddings/embedding-config.model';
import { GetLlmConfigRequest } from '../../features/settings-dialog/models/llms/LLM_config.model';
import { EmbeddingConfigsService } from '../../features/settings-dialog/services/embeddings/embedding_configs.service';
import { FullEmbeddingConfigService } from '../../features/settings-dialog/services/embeddings/full-embedding.service';
import { FullEmbeddingConfig } from '../../features/settings-dialog/services/embeddings/full-embedding.service';
import { FullLLMConfigService } from '../../features/settings-dialog/services/llms/full-llm-config.service';
import { FullLLMConfig } from '../../features/settings-dialog/services/llms/full-llm-config.service';
import { LLM_Config_Service } from '../../features/settings-dialog/services/llms/llm-config.service';
import { EmbeddingModelSelectorComponent } from '../../shared/components/embedding-model-selector/embedding-model-selector.component';
import { HelpTooltipComponent } from '../../shared/components/help-tooltip/help-tooltip.component';
import { LlmModelSelectorComponent } from '../../shared/components/llm-model-selector/llm-model-selector.component';

@Component({
    selector: 'app-settings-section',
    templateUrl: './settings-section.component.html',
    styleUrls: ['./settings-section.component.scss'],
    standalone: true,
    imports: [
        CommonModule,
        FormsModule,
        HelpTooltipComponent,
        LlmModelSelectorComponent,
        EmbeddingModelSelectorComponent,
    ],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class SettingsSectionComponent implements OnInit, OnChanges {
    @Input() public project!: GetProjectRequest;
    @Output() public settingsChange = new EventEmitter<Partial<GetProjectRequest>>();

    // Project settings as signals
    public memory = signal<boolean>(false);
    public cache = signal<boolean>(false);
    public max_rpm = signal<number>(15);
    public process = signal<'sequential' | 'hierarchical'>('sequential');
    public manager_llm_config = signal<number | null>(null);
    public memory_llm_config = signal<number | null>(null);
    public embedding_config = signal<number | null>(null);
    public settings = signal<{
        temperature: number;
        cache: boolean;
        full_output: boolean;
        planning: boolean;
    }>({
        temperature: 0.7,
        cache: false,
        full_output: false,
        planning: false,
    });

    // Other signals for reactive data
    public availableLLMs = signal<GetLlmConfigRequest[]>([]);
    public embeddingConfigs = signal<GetEmbeddingConfigRequest[]>([]);

    // Full config objects for the selectors
    public fullLLMConfigs = signal<FullLLMConfig[]>([]);
    public fullEmbeddingConfigs = signal<FullEmbeddingConfig[]>([]);

    public isLoading = signal(true);
    public configsLoaded = signal(false);

    private tempCurrentValue: number = 0;
    private rpmCurrentValue: number = 15;

    constructor(
        private llmConfigService: LLM_Config_Service,
        private embeddingConfigService: EmbeddingConfigsService,
        private fullLLMConfigService: FullLLMConfigService,
        private fullEmbeddingConfigService: FullEmbeddingConfigService,
        private cdr: ChangeDetectorRef
    ) {}

    public ngOnInit(): void {
        this.loadConfigurations();
        this.initializeBasicSettings();
    }

    public ngOnChanges(changes: SimpleChanges): void {
        if (changes['project'] && !changes['project'].firstChange) {
            this.initializeBasicSettings();
            if (this.configsLoaded()) {
                this.initializeHierarchicalSettings();
            }
        }
    }

    public getParsedThreshold(value: string): number {
        return parseFloat(value);
    }

    private initializeBasicSettings(): void {
        if (this.project) {
            this.memory.set(this.project.memory ?? false);
            this.cache.set(this.project.cache ?? false);
            const rpm = this.project.max_rpm ?? 15;
            this.max_rpm.set(rpm);
            this.rpmCurrentValue = rpm;
            this.process.set(this.project.process ?? 'sequential');

            const temperature = this.project.default_temperature ?? 0.7;
            this.tempCurrentValue = Math.round(temperature * 100);

            this.settings.set({
                temperature: temperature,
                cache: this.project.cache ?? false,
                full_output: this.project.full_output ?? false,
                planning: this.project.planning ?? false,
            });
            //   this.cdr.markForCheck();
        }
    }

    private initializeHierarchicalSettings(): void {
        if (this.project) {
            this.manager_llm_config.set(this.project.manager_llm_config);
            this.memory_llm_config.set(this.project.memory_llm_config);
            this.embedding_config.set(this.project.embedding_config);

            //   this.cdr.markForCheck();
        }
    }

    private loadConfigurations(): void {
        this.isLoading.set(true);
        this.configsLoaded.set(false);

        // Fetch LLM configs
        this.llmConfigService.getAllConfigsLLM().subscribe({
            next: (configs) => {
                this.availableLLMs.set(configs);
                this.checkLoadingComplete();
            },
            error: (error) => {
                console.error('Error fetching LLM configs:', error);
                this.checkLoadingComplete();
            },
        });

        // Fetch embedding configs
        this.embeddingConfigService.getEmbeddingConfigs().subscribe({
            next: (configs) => {
                this.embeddingConfigs.set(configs);
                this.checkLoadingComplete();
            },
            error: (error) => {
                console.error('Error fetching embedding configs:', error);
                this.checkLoadingComplete();
            },
        });

        // Fetch full LLM configs for the selector
        this.fullLLMConfigService.getFullLLMConfigs().subscribe({
            next: (configs) => {
                this.fullLLMConfigs.set(configs);
            },
            error: (error) => {
                console.error('Error fetching full LLM configs:', error);
            },
        });

        // Fetch full embedding configs for the selector
        this.fullEmbeddingConfigService.getFullEmbeddingConfigs().subscribe({
            next: (configs) => {
                this.fullEmbeddingConfigs.set(configs);
            },
            error: (error) => {
                console.error('Error fetching full embedding configs:', error);
            },
        });
    }

    private checkLoadingComplete(): void {
        if (this.availableLLMs().length > 0 && this.embeddingConfigs().length > 0) {
            this.isLoading.set(false);
            this.configsLoaded.set(true);
            this.initializeHierarchicalSettings();
            this.cdr.markForCheck();
        }
    }

    // Event handlers
    public toggleMemory(): void {
        const newValue = !this.memory();
        this.memory.set(newValue);
        this.onSettingChange('memory', newValue);
    }

    public toggleCache(): void {
        const newValue = !this.cache();
        this.cache.set(newValue);
        this.onSettingChange('cache', newValue);
    }

    public toggleProcess(): void {
        const newValue = this.process() === 'sequential' ? 'hierarchical' : 'sequential';
        this.process.set(newValue);
        this.onSettingChange('process', newValue);
    }

    public toggleSetting(setting: 'cache' | 'full_output' | 'planning'): void {
        const currentSettings = this.settings();
        const newValue = !currentSettings[setting];

        this.settings.set({
            ...currentSettings,
            [setting]: newValue,
        });

        this.onSettingChange(setting, newValue);
    }

    public onLLMConfigChange(): void {
        this.onSettingChange('manager_llm_config', this.manager_llm_config());
    }

    public onMemoryLLMConfigChange(): void {
        this.onSettingChange('memory_llm_config', this.memory_llm_config());
    }

    public onEmbeddingConfigChange(): void {
        this.onSettingChange('embedding_config', this.embedding_config());
    }

    public onSettingChange(setting: string, value: unknown): void {
        if (!this.project || !this.project.id) return;

        const updateData: Partial<GetProjectRequest> = {
            [setting]: value,
        };

        // Emit the change to the parent component instead of calling API directly
        this.settingsChange.emit(updateData);
    }

    public onTemperatureSliderMove(value: number): void {
        this.tempCurrentValue = value;
        // Update local UI without saving
        const currentSettings = this.settings();
        const newTemperature = parseFloat((value / 100).toFixed(1));
        this.settings.set({
            ...currentSettings,
            temperature: newTemperature,
        });
    }

    public onTemperatureSliderEnd(): void {
        // Save changes only when slider movement ends
        const newTemperature = parseFloat((this.tempCurrentValue / 100).toFixed(1));
        this.onSettingChange('default_temperature', newTemperature);
    }

    public get temperaturePercent(): number {
        return Math.round(this.settings().temperature * 100);
    }

    public set temperaturePercent(val: number) {
        const currentSettings = this.settings();
        const newTemperature = parseFloat((val / 100).toFixed(1));

        this.settings.set({
            ...currentSettings,
            temperature: newTemperature,
        });

        this.onSettingChange('default_temperature', newTemperature);
    }

    public onRpmSliderMove(value: number): void {
        this.rpmCurrentValue = value;
        this.max_rpm.set(value);
    }

    public onRpmSliderEnd(): void {
        // Only save changes when slider movement ends
        this.onSettingChange('max_rpm', this.rpmCurrentValue);
    }

    // Текущее значение ползунка (аналог rpmCurrentValue)
    // public thresholdCurrentValue: string = this.settings().similarity_threshold;
    // public searchLimitCurrentValue: number = this.settings().search_limit;

    // // Вызывается при движении ползунка
    // public onThresholdSliderMove(value: unknown): void {
    //     this.thresholdCurrentValue = value.toString();
    //     const currentSettings = this.settings();
    //     this.settings.set({
    //         ...currentSettings,
    //         similarity_threshold: value.toString(),
    //     });
    // }

    // // Вызывается при отпускании ползунка
    // public onThresholdSliderEnd(): void {
    //     this.onSettingChange(
    //         'similarity_threshold',
    //         this.thresholdCurrentValue
    //     );
    // }

    // public onSearchLimitSliderMove(value: number): void {
    //     this.searchLimitCurrentValue = value;
    //     const currentSettings = this.settings();
    //     this.settings.set({
    //         ...currentSettings,
    //         search_limit: value,
    //     });
    // }

    // public onSearchLimitSliderEnd(): void {
    //     this.onSettingChange('search_limit', this.searchLimitCurrentValue);
    // }
}
