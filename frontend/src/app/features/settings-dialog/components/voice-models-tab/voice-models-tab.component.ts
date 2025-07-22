import {
  ChangeDetectionStrategy,
  Component,
  OnInit,
  signal,
  inject,
} from '@angular/core';
import { CommonModule } from '@angular/common';
import { AppIconComponent } from '../../../../shared/components/app-icon/app-icon.component';
import {
  FullRealtimeConfig,
  FullRealtimeConfigService,
} from '../../services/realtime-llms/full-reamtime-config.service';
import { LoadingState } from '../../../../core/enums/loading-state.enum';
import { VoiceConfigItemComponent } from './voice-config-item/voice-config-item.component';
import { ButtonComponent } from '../../../../shared/components/buttons/button/button.component';
import { RealtimeModelConfigsService } from '../../services/realtime-llms/real-time-model-config.service';
import { UpdateRealtimeModelConfigRequest } from '../../models/realtime-voice/realtime-llm-config.model';
import { Dialog } from '@angular/cdk/dialog';
import { AddVoiceConfigDialogComponent } from './add-voice-config-dialog/add-voice-config-dialog.component';
import { EditVoiceConfigDialogComponent } from './add-voice-config-dialog/edit-voice-config-dialog.component';

@Component({
  selector: 'app-voice-models-tab',
  standalone: true,
  imports: [CommonModule, VoiceConfigItemComponent, ButtonComponent],
  templateUrl: './voice-models-tab.component.html',
  styleUrls: ['./voice-models-tab.component.scss'],
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class VoiceModelsTabComponent implements OnInit {
  private readonly fullRealtimeConfigService = inject(
    FullRealtimeConfigService
  );
  private readonly realtimeConfigService = inject(RealtimeModelConfigsService);
  private readonly dialog = inject(Dialog);

  public voiceConfigs = signal<FullRealtimeConfig[]>([]);
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
    const dialogRef = this.dialog.open(AddVoiceConfigDialogComponent, {
      width: '500px',
      disableClose: true,
    });
    dialogRef.closed.subscribe((result) => {
      if (result === true) {
        this.refreshData();
      }
    });
  }

  public onFavoriteToggled(event: { id: string | number; value: boolean }) {
    console.log('Favorite toggled:', event);
  }

  public onEnabledToggled(event: { id: string | number; value: boolean }) {
    console.log('Enabled toggled:', event);
    const config: FullRealtimeConfig | undefined = this.voiceConfigs().find(
      (c) => c.id === event.id
    );
    if (!config) return;
    const updateReq: UpdateRealtimeModelConfigRequest = {
      id: config.id,
      custom_name: config.custom_name,
      api_key: config.api_key,
      realtime_model: config.realtime_model,
      is_visible: event.value as any,
    } as any;
    this.realtimeConfigService.updateConfig(updateReq).subscribe({
      next: (updated) => {
        this.voiceConfigs.set(
          this.voiceConfigs().map((c) =>
            c.id === updated.id ? { ...c, is_visible: event.value } : c
          )
        );
      },
      error: (err) => {
        console.error('Failed to update config:', err);
      },
    });
  }

  public onConfigureClicked(id: string | number) {
    const config = this.voiceConfigs().find((c) => c.id === id);
    if (!config) return;
    const dialogRef = this.dialog.open(EditVoiceConfigDialogComponent, {
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
    this.realtimeConfigService.deleteConfig(Number(id)).subscribe({
      next: () => {
        this.voiceConfigs.set(this.voiceConfigs().filter((c) => c.id !== id));
      },
      error: (err) => {
        console.error('Failed to delete config:', err);
      },
    });
  }

  private loadConfigs(): void {
    this.status.set(LoadingState.LOADING);

    this.fullRealtimeConfigService.getFullRealtimeConfigs().subscribe({
      next: (response) => {
        this.voiceConfigs.set(response.fullConfigs);
        this.status.set(LoadingState.LOADED);
      },
      error: (err) => {
        console.error('Failed to load voice configurations:', err);
        this.errorMessage.set(
          'Failed to load voice configurations. Please try again.'
        );
        this.status.set(LoadingState.ERROR);
      },
    });
  }
}
