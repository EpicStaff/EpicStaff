import { Component } from '@angular/core';
import { ICellRendererAngularComp } from 'ag-grid-angular';
import { ICellRendererParams } from 'ag-grid-community';
import { CommonModule } from '@angular/common';
import { MergedConfig } from '../../../../../services/full-agent.service';
import { AppIconComponent } from '../../../../../shared/components/app-icon/app-icon.component';
import { getProviderIconPath } from '../../../../../features/settings-dialog/utils/get-provider-icon';

@Component({
  selector: 'app-config-cell-renderer',
  standalone: true,
  imports: [CommonModule, AppIconComponent],
  template: `
    <div class="configs-cell-wrapper">
      <div *ngIf="!configs || configs.length === 0" class="no-configs">
        No configurations assigned
      </div>

      <div
        *ngFor="let config of configs"
        class="config-item"
        [ngClass]="config.type"
      >
        <app-icon
          [icon]="getProviderIcon(config)"
          size="20px"
          [ariaLabel]="config.provider_name || ''"
          class="provider-icon"
        ></app-icon>

        <div class="item-content">
          <div class="item-text">
            {{ config.model_name }}
            <span *ngIf="config.custom_name" class="custom-name">
              ({{ config.custom_name }})
            </span>
          </div>
        </div>
      </div>
    </div>
  `,
  styles: `
    .configs-cell-wrapper {
      display: flex;
      flex-direction: column;
      gap: 8px;
      padding: 10px 5px;
      height: 100%;
    }

    .config-item {
      display: flex;
      align-items: center;
      background-color: #2a2a2a;
      border-radius: 4px;
      padding: 8px;
      border: 1px solid #404040;
      transition: background-color 0.3s, border 0.3s;
      width: 100%;
    }

    .config-item:hover {
      background-color: #3a3a3a;
    }

    .provider-icon {
      flex-shrink: 0;
      width: 20px;
      height: 20px;
      margin-right: 8px;
      border-radius: 4px;
      display: flex;
      align-items: center;
      justify-content: center;
    }

    .item-content {
      display: flex;
      flex-direction: column;
      flex: 1;
      min-width: 0;
    }

    .item-text {
      line-height: 1.3;
      font-size: 13px;
      font-weight: 500;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
      min-width: 0;
      max-width: 100%;
    }

    .custom-name {
      color: #aaa;
      margin-left: 5px;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }

    .no-configs {
      height: 100%;
      display: flex;
      align-items: flex-end;
      justify-content: flex-end;
      color: #aaa;
      font-style: italic;
      padding: 4px 8px;
      font-size: 0.8rem;
    }
  `,
})
export class ConfigCellRendererComponent implements ICellRendererAngularComp {
  configs: MergedConfig[] = [];

  agInit(params: ICellRendererParams): void {
    this.configs = params.value || [];
  }

  refresh(params: ICellRendererParams): boolean {
    this.configs = params.value || [];
    return true;
  }

  getProviderIcon(config: MergedConfig): string {
    return getProviderIconPath(config.provider_name);
  }
}
