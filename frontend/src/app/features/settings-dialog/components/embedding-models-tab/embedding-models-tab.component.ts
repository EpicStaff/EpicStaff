import {
  ChangeDetectionStrategy,
  Component,
  OnInit,
  signal,
  inject,
} from '@angular/core';
import { CommonModule } from '@angular/common';
import { Dialog } from '@angular/cdk/dialog';

import {
  FullEmbeddingConfig,
  FullEmbeddingConfigService,
} from '../../services/embeddings/full-embedding.service';
import { LoadingState } from '../../../../core/enums/loading-state.enum';
import { EmbeddingConfigItemComponent } from './embedding-config-item/embedding-config-item.component';
import { ButtonComponent } from '../../../../shared/components/buttons/button/button.component';
import { AddEmbeddingConfigDialogComponent } from './add-embedding-config-dialog/add-embedding-config-dialog.component';
import { EditEmbeddingConfigDialogComponent } from './add-embedding-config-dialog/edit-embedding-config-dialog.component';
import { EmbeddingConfigsService } from '../../services/embeddings/embedding_configs.service';
import { EmbeddingConfig } from '../../models/embeddings/embedding-config.model';

@Component({
  selector: 'app-embedding-models-tab',
  standalone: true,
  imports: [
    CommonModule,
    EmbeddingConfigItemComponent,
    ButtonComponent,
  ],
  templateUrl: './embedding-models-tab.component.html',
  styleUrls: ['./embedding-models-tab.component.scss'],
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class EmbeddingModelsTabComponent implements OnInit {
  private readonly fullEmbeddingConfigService = inject(
    FullEmbeddingConfigService
  );
  private readonly dialog = inject(Dialog);
  private readonly embeddingConfigService = inject(EmbeddingConfigsService);

  public embeddingConfigs = signal<FullEmbeddingConfig[]>([]);
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
    const dialogRef = this.dialog.open(AddEmbeddingConfigDialogComponent, {
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

    this.fullEmbeddingConfigService.getFullEmbeddingConfigs().subscribe({
      next: (configs) => {
        this.embeddingConfigs.set(configs);
        this.status.set(LoadingState.LOADED);
      },
      error: (err) => {
        console.error('Failed to load embedding configurations:', err);
        this.errorMessage.set(
          'Failed to load embedding configurations. Please try again.'
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
    const config: FullEmbeddingConfig | undefined =
      this.embeddingConfigs().find((c) => c.id === event.id);
    if (!config) return;

    // Create an update request from the existing config
    const updateReq: EmbeddingConfig = {
      id: Number(config.id),
      model: config.model,
      custom_name: config.custom_name,
      api_key: config.api_key,
      is_visible: event.value,
      task_type: config.task_type,
    };

    this.embeddingConfigService.updateEmbeddingConfig(updateReq).subscribe({
      next: (updated) => {
        // Update local array
        this.embeddingConfigs.set(
          this.embeddingConfigs().map((c) =>
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

    const config = this.embeddingConfigs().find((c) => c.id === id);
    if (!config) return;
    const dialogRef = this.dialog.open(EditEmbeddingConfigDialogComponent, {
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
    this.embeddingConfigService.deleteEmbeddingConfig(Number(id)).subscribe({
      next: () => {
        this.embeddingConfigs.set(
          this.embeddingConfigs().filter((c) => c.id !== id)
        );
      },
      error: (err) => {
        console.error('Failed to delete config:', err);
      },
    });
  }
}
