import { CommonModule } from '@angular/common';
import { Component } from '@angular/core';
import { MatTooltipModule } from '@angular/material/tooltip';
import { IHeaderParams } from 'ag-grid-community';

import { AppSvgIconComponent } from '../../../../../shared/components/app-svg-icon/app-svg-icon.component';

@Component({
    selector: 'app-knowledge-query-header',
    standalone: true,
    imports: [CommonModule, AppSvgIconComponent, MatTooltipModule],
    template: `
        <div class="knowledge-header">
            <span class="knowledge-label">Knowledge Query</span>
            <app-svg-icon
                icon="help"
                size="1rem"
                class="create-agent__help-icon"
                matTooltip="Enter a query for knowledge extraction, or leave this field empty to auto-generate it"
                matTooltipPosition="above"
                matTooltipClass="create-agent__tooltip"
            />
        </div>
    `,
    styles: [
        `
            :host {
                display: flex;
                align-items: center;
                width: 100%;
            }
            .knowledge-header {
                display: flex;
                align-items: center;
                gap: 6px;
            }
            .create-agent__help-icon {
                color: var(--color-text-secondary, #666);
                cursor: help;
                opacity: 0.7;
                transition: opacity 0.2s ease;
            }
        `,
    ],
})
export class KnowledgeQueryHeaderComponent {
    params!: IHeaderParams;

    agInit(params: IHeaderParams): void {
        this.params = params;
    }

    refresh(): boolean {
        return false;
    }
}
