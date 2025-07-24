import {
  ChangeDetectionStrategy,
  Component,
  Input,
  Output,
  EventEmitter,
} from '@angular/core';
import { CommonModule } from '@angular/common';
import { AppIconComponent } from '../../../../../shared/components/app-icon/app-icon.component';
import { IconButtonComponent } from '../../../../../shared/components/buttons/icon-button/icon-button.component';
import { ButtonComponent } from '../../../../../shared/components/buttons/button/button.component';
import { FullEmbeddingConfig } from '../../../services/embeddings/full-embedding.service';
import { getProviderIconPath } from '../../../utils/get-provider-icon';
import { ToggleSwitchComponent } from '../../../../../shared/components/form-controls/toggle-switch/toggle-switch.component';

@Component({
  selector: 'app-embedding-config-item',
  standalone: true,
  imports: [
    CommonModule,
    AppIconComponent,
    IconButtonComponent,
    ButtonComponent,
    ToggleSwitchComponent,
  ],
  templateUrl: './embedding-config-item.component.html',
  styleUrls: ['./embedding-config-item.component.scss'],
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class EmbeddingConfigItemComponent {
  @Input() config!: FullEmbeddingConfig;

  @Output() favoriteToggled = new EventEmitter<{
    id: string | number;
    value: boolean;
  }>();
  @Output() enabledToggled = new EventEmitter<{
    id: string | number;
    value: boolean;
  }>();
  @Output() configureClicked = new EventEmitter<string | number>();
  @Output() deleteClicked = new EventEmitter<string | number>();

  public isFavorite: boolean = false;

  public getProviderIcon(): string {
    return getProviderIconPath(this.config.providerDetails?.name);
  }

  public toggleFavorite(): void {
    this.isFavorite = !this.isFavorite;
    this.favoriteToggled.emit({ id: this.config.id, value: this.isFavorite });
  }

  public getFavoriteButtonColor(): string {
    return this.isFavorite ? '#ffb800' : 'var(--color-text-secondary)';
  }

  public onEnabledToggle(value: boolean): void {
    this.enabledToggled.emit({ id: this.config.id, value });
  }

  public onConfigure(): void {
    this.configureClicked.emit(this.config.id);
  }

  public onDelete(): void {
    this.deleteClicked.emit(this.config.id);
  }
}
