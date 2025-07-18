import {
  Component,
  ChangeDetectionStrategy,
  Input,
  Output,
  EventEmitter,
  OnInit,
  OnChanges,
  SimpleChanges,
  ChangeDetectorRef,
  signal,
} from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';

import { GetProjectRequest } from '../../features/projects/models/project.model';
import { LLM_Config_Service } from '../../features/settings-dialog/services/llms/LLM_config.service';
import { EmbeddingConfigsService } from '../../features/settings-dialog/services/embeddings/embedding_configs.service';
import { GetLlmConfigRequest } from '../../features/settings-dialog/models/llms/LLM_config.model';
import { GetEmbeddingConfigRequest } from '../../features/settings-dialog/models/embeddings/embedding-config.model';

import { HelpTooltipComponent } from '../../shared/components/help-tooltip/help-tooltip.component';

import { LlmModelSelectorComponent } from '../../shared/components/llm-model-selector/llm-model-selector.component';
import { EmbeddingModelSelectorComponent } from '../../shared/components/embedding-model-selector/embedding-model-selector.component';
import { FullLLMConfigService } from '../../features/settings-dialog/services/llms/full-llm-config.service';
import { FullEmbeddingConfigService } from '../../features/settings-dialog/services/embeddings/full-embedding.service';

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
  @Output() public settingsChange = new EventEmitter<
    Partial<GetProjectRequest>
  >();

  // Project settings as signals
  public memory = signal<boolean>(false);
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
  public fullLLMConfigs = signal<any[]>([]);
  public fullEmbeddingConfigs = signal<any[]>([]);

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

  private initializeBasicSettings(): void {
    if (this.project) {
      this.memory.set(this.project.memory ?? false);
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

  public toggleProcess(): void {
    const newValue =
      this.process() === 'sequential' ? 'hierarchical' : 'sequential';
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

  public onSettingChange(setting: string, value: any): void {
    if (!this.project || !this.project.id) return;

    const updateData: Partial<GetProjectRequest> = {
      [setting]: value,
    };

    console.log(`🔧 Settings component emitting change:`, {
      setting,
      value,
      updateData,
    });

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
}
