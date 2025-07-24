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
import { AddLlmConfigDialogComponent } from './add-llm-config-dialog/add-llm-config-dialog.component';
import { EditLlmConfigDialogComponent } from './add-llm-config-dialog/edit-llm-config-dialog.component';
import {
  FullLLMConfigService,
  FullLLMConfig,
} from '../../services/llms/full-llm-config.service';
import { LLM_Config_Service } from '../../services/llms/LLM_config.service';
import { UpdateLLMConfigRequest } from '../../models/llms/LLM_config.model';

@Component({
  selector: 'app-llm-models-tab',
  standalone: true,
  imports: [
    CommonModule,
    AppIconComponent,
    LlmConfigItemComponent,
    ButtonComponent,
  ],
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
        // Refresh the list if a new config was added
        this.refreshData();
      }
    });
  }

  private loadConfigs(): void {
    this.status.set(LoadingState.LOADING);

    this.fullLlmConfigService.getFullLLMConfigs().subscribe({
      next: (configs) => {
        this.llmConfigs.set(configs);
        console.log('configs', configs);
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
    console.log('Favorite toggled:', event);
  }

  public onEnabledToggled(event: { id: string | number; value: boolean }) {
    console.log('Enabled toggled:', event);
    const config: FullLLMConfig | undefined = this.llmConfigs().find(
      (c) => c.id === event.id
    );
    if (!config) return;
    const updateReq: UpdateLLMConfigRequest = {
      id: config.id,
      temperature: config.temperature,
      num_ctx: config.num_ctx,
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
            c.id === updated.id ? { ...c, is_visible: updated.is_visible } : c
          )
        );
      },
      error: (err) => {
        console.error('Failed to update config:', err);
      },
    });
  }

  public onConfigureClicked(id: string | number) {
    console.log('Configure clicked:', id);
    const config = this.llmConfigs().find((c) => c.id === id);
    if (!config) return;
    const dialogRef = this.dialog.open(EditLlmConfigDialogComponent, {
      width: '500px',
      disableClose: true,
      data: { ...config },
    });
    dialogRef.closed.subscribe((result) => {
      if (result === true) {
        this.refreshData();
      }
    });
  }

  public onDeleteClicked(id: string | number) {
    console.log('Delete clicked:', id);
    this.llmConfigService.deleteConfig(Number(id)).subscribe({
      next: () => {
        this.llmConfigs.set(this.llmConfigs().filter((c) => c.id !== id));
      },
      error: (err) => {
        console.error('Failed to delete config:', err);
      },
    });
  }
}
