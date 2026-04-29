import { CommonModule } from '@angular/common';
import { Component } from '@angular/core';
import { IHeaderParams } from 'ag-grid-community';

import { HelpTooltipComponent } from '../../../../../shared/components/help-tooltip/help-tooltip.component';

@Component({
    selector: 'app-knowledge-query-header',
    standalone: true,
    imports: [CommonModule, HelpTooltipComponent],
    template: `
        <div class="knowledge-header">
            <span class="knowledge-label">Knowledge Query</span>
            <app-help-tooltip
                class="create-agent__help-icon"
                text="Enter a query for knowledge extraction, or leave this field empty to auto-generate it"
                position="top"
                tooltipClass="create-agent__tooltip"
                size="1rem"
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
