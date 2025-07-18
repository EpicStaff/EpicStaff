import {
  Component,
  Input,
  Output,
  EventEmitter,
  ChangeDetectionStrategy,
} from '@angular/core';
import { CommonModule } from '@angular/common';
import { FullLLMConfig } from '../../../../features/settings-dialog/services/llms/full-llm-config.service';
import { AppIconComponent } from '../../app-icon/app-icon.component';
import { getProviderIconPath } from '../../../../features/settings-dialog/utils/get-provider-icon';

@Component({
  selector: 'app-llm-model-item',
  standalone: true,
  imports: [CommonModule, AppIconComponent],
  template: `
    <div class="model-item" [class.selected]="isSelected" (click)="onSelect()">
      <app-icon
        [icon]="getProviderIcon()"
        size="20px"
        [ariaLabel]="config.providerDetails?.name || ''"
        class="provider-icon"
      >
      </app-icon>
      <div class="model-text">
        <span class="model-name">{{
          config.modelDetails?.name || 'Unknown Model'
        }}</span>
        <span *ngIf="config.custom_name" class="custom-name">
          ({{ config.custom_name }})
        </span>
      </div>
    </div>
  `,
  styles: [
    `
      .model-item {
        display: flex;
        align-items: center;
        gap: 10px;
        padding: 8px 12px;
        margin-bottom: 4px;
        cursor: pointer;
        transition: background-color 0.2s ease;
        border-radius: 4px;
      }

      .model-item:hover {
        background-color: rgba(104, 95, 255, 0.08);
      }

      .model-item.selected {
        background-color: rgba(104, 95, 255, 0.12);
      }

      .provider-icon {
        flex-shrink: 0;
      }

      .model-text {
        display: flex;
        flex-direction: row;
        align-items: center;
        gap: 6px;
        overflow: hidden;
        text-overflow: ellipsis;
        white-space: nowrap;
      }

      .model-name {
        font-size: 0.875rem;
        color: var(--color-text-primary);
      }

      .custom-name {
        font-size: 0.75rem;
        color: var(--color-text-secondary);
        opacity: 0.8;
      }
    `,
  ],
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class LlmModelItemComponent {
  @Input() config!: FullLLMConfig;
  @Input() isSelected: boolean = false;

  @Output() selected = new EventEmitter<FullLLMConfig>();

  onSelect(): void {
    this.selected.emit(this.config);
  }

  getProviderIcon(): string {
    if (!this.config || !this.config.providerDetails?.name) {
      return 'llm-providers-logos/default';
    }
    return getProviderIconPath(this.config.providerDetails.name);
  }
}
