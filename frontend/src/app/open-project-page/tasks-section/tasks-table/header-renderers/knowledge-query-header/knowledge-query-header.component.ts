import { Component } from '@angular/core';
import { IHeaderParams } from 'ag-grid-community';
import { CommonModule } from '@angular/common';
import { MatIconModule } from '@angular/material/icon';
import { MatTooltipModule } from '@angular/material/tooltip';

@Component({
    selector: 'app-knowledge-query-header',
    standalone: true,
    imports: [CommonModule, MatIconModule, MatTooltipModule],
    template: `
    <div class="knowledge-header">
      <span class="knowledge-label">Knowledge Query</span>
      <mat-icon
        class="create-agent__help-icon"
        matTooltip="Choose a knowledge source to provide additional context and information for this agent."
        matTooltipPosition="above"
        matTooltipClass="create-agent__tooltip"
        >
        help_outline
      </mat-icon>
    </div>
  `,
    styles: [
        `:host { display: flex; align-items: center; width: 100%; }
    .knowledge-header { display: flex; align-items: center; gap: 6px; }
    .create-agent__help-icon { font-size: 1rem;
    width: 1rem;
    height: 1rem;
    color: var(--color-text-secondary, #666);
    cursor: help;
    opacity: 0.7;
    transition: opacity 0.2s ease; }
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
