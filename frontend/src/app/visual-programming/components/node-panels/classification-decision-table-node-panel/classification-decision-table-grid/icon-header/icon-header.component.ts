import { CommonModule } from '@angular/common';
import { Component } from '@angular/core';
import { IHeaderAngularComp } from 'ag-grid-angular';
import { IHeaderParams } from 'ag-grid-community';

import { AppSvgIconComponent } from '../../../../../../shared/components/app-svg-icon/app-svg-icon.component';

export interface IconHeaderParams extends IHeaderParams {
    iconClass?: string;
    tooltip?: string;
    label?: string;
    variant?: 'default' | 'delete';
    onIconClick?: (event: MouseEvent) => void;
}

@Component({
    selector: 'app-icon-header',
    imports: [CommonModule, AppSvgIconComponent],
    template: `
        <div
            class="icon-header"
            [title]="tooltip"
        >
            @if (label) {
                <span class="icon-header-label">{{ label }}</span>
            }
            @if (variant === 'delete') {
                <app-svg-icon
                    class="icon-header-delete-svg"
                    icon="trash"
                    size="14px"
                    (click)="onIconClick ? onIconClick($event) : null"
                ></app-svg-icon>
            } @else {
                <i
                    [class]="iconClass"
                    [class.icon-header-clickable]="!!onIconClick"
                    (click)="onIconClick ? onIconClick($event) : null"
                ></i>
            }
        </div>
    `,
    styles: [
        `
            .icon-header {
                display: flex;
                align-items: center;
                justify-content: space-between;
                width: 100%;
                height: 100%;
                cursor: default;
                gap: 4px;
                padding: 0 4px;
            }
            .icon-header-label {
                font-size: 0.85rem;
                color: rgba(255, 255, 255, 0.9);
                font-weight: 500;
                flex: 1;
                overflow: hidden;
                text-overflow: ellipsis;
                white-space: nowrap;
            }
            .icon-header i {
                font-size: 0.85rem;
                color: rgba(255, 255, 255, 0.7);
                flex-shrink: 0;
            }
            /* NOTE: kept in sync with .chm-icon-clickable in column-header-menu.component.ts */
            .icon-header-clickable {
                cursor: pointer;
                background: rgba(104, 95, 255, 0.25);
                border: 1px solid rgba(104, 95, 255, 0.5);
                border-radius: 50%;
                width: 20px;
                height: 20px;
                display: flex;
                align-items: center;
                justify-content: center;
                font-size: 0.75rem !important;
                color: #a89fff !important;
                transition:
                    background 0.15s ease,
                    color 0.15s ease;
                flex-shrink: 0;
            }
            .icon-header-clickable:hover {
                background: rgba(104, 95, 255, 0.5) !important;
                color: #fff !important;
                border-color: var(--accent-color);
            }
            .icon-header-delete {
                cursor: pointer;
                font-size: 0.8rem !important;
                color: rgba(255, 255, 255, 0.4) !important;
                flex-shrink: 0;
                transition: color 0.15s ease;
                padding: 2px;
            }
            .icon-header-delete:hover {
                color: rgba(255, 100, 100, 0.85) !important;
            }
            .icon-header-delete-svg {
                cursor: pointer;
                color: var(--purple-primary);
            }
        `,
    ],
})
export class IconHeaderComponent implements IHeaderAngularComp {
    public iconClass = '';
    public tooltip = '';
    public label = '';
    public variant: 'default' | 'delete' = 'default';
    public onIconClick: ((event: MouseEvent) => void) | undefined = undefined;

    agInit(params: IconHeaderParams): void {
        this.iconClass = params.iconClass || '';
        this.tooltip = params.tooltip || '';
        this.label = params.label || '';
        this.variant = params.variant || 'default';
        this.onIconClick = params.onIconClick;
    }

    refresh(): boolean {
        return true;
    }
}
