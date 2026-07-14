import { CommonModule } from '@angular/common';
import { Component } from '@angular/core';
import { AppSvgIconComponent } from '@shared/components';
import { getProviderIconPath } from '@shared/utils';
import { ICellRendererAngularComp } from 'ag-grid-angular';
import { ICellRendererParams } from 'ag-grid-community';

import { MergedConfig } from '../../../../../features/staff/services/full-agent.service';

@Component({
    selector: 'app-config-cell-renderer',
    standalone: true,
    imports: [CommonModule, AppSvgIconComponent],
    template: `
        <div class="configs-cell-wrapper">
            <div
                *ngIf="!configs || configs.length === 0"
                class="no-configs"
            >
                No configurations assigned
            </div>

            <div
                *ngFor="let config of configs"
                class="config-item"
                [ngClass]="config.type"
            >
                <app-svg-icon
                    [icon]="getProviderIcon(config)"
                    size="20px"
                    [ariaLabel]="config.provider_name || ''"
                    class="provider-icon"
                />

                <div class="item-content">
                    <div class="item-text">
                        {{ config.model_name }}
                        <span
                            *ngIf="config.custom_name"
                            class="custom-name"
                        >
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
            gap: var(--space-sm);
            padding: var(--space-md) var(--space-xs);
            height: 100%;
        }

        .config-item {
            display: flex;
            align-items: center;
            background-color: var(--graphite-780);
            border-radius: var(--radius-sm);
            padding: var(--space-sm);
            border: 1px solid #404040;
            transition:
                background-color 0.3s,
                border 0.3s;
            width: 100%;
        }

        .config-item:hover {
            background-color: var(--graphite-600);
        }

        .provider-icon {
            flex-shrink: 0;
            width: 20px;
            height: 20px;
            margin-right: var(--space-sm);
            border-radius: var(--radius-sm);
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
            font-size: var(--font-size-sm);
            font-weight: var(--font-weight-medium);
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
            min-width: 0;
            max-width: 100%;
        }

        .custom-name {
            color: #aaa;
            margin-left: var(--space-xs);
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
            padding: var(--space-2xs) var(--space-sm);
            font-size: var(--font-size-sm);
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
