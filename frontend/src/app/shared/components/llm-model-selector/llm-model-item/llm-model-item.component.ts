import { ChangeDetectionStrategy, Component, EventEmitter, Input, Output } from '@angular/core';
import { MatTooltip } from '@angular/material/tooltip';
import { FullLLMConfig, FullRealtimeConfig } from '@shared/services';

import { TooltipOnOverflowDirective } from '../../../directives/tooltip-on-overflow.directive';

@Component({
    selector: 'app-llm-model-item',
    imports: [MatTooltip, TooltipOnOverflowDirective],
    template: `
        <button
            type="button"
            class="model-item"
            [class.selected]="isSelected"
            [attr.aria-pressed]="isSelected"
            appTooltipOnOverflow=".model-text"
            [matTooltip]="config.modelDetails?.name || 'Unknown Model'"
            (click)="onSelect()"
        >
            <span class="model-text">
                <span class="model-name">{{ config.modelDetails?.name || 'Unknown Model' }}</span>
            </span>
            @if (config.custom_name) {
                <span class="custom-name">({{ config.custom_name }})</span>
            }
        </button>
    `,
    styles: [
        `
            .model-item {
                display: flex;
                width: 100%;
                border: none;
                background: transparent;
                color: inherit;
                font-family: inherit;
                text-align: left;
                align-items: center;
                gap: 10px;
                height: 40px;
                flex-shrink: 0;
                padding: 0.25rem 1rem;
                cursor: pointer;
                border: 1px solid var(--color-divider-subtle);
                border-radius: 4px;
                background-color: var(--color-ks-line);
                transition:
                    border-color 0.15s ease,
                    background-color 0.15s ease;
            }

            .model-item:is(:hover, :focus-visible) {
                background-color: var(--color-ks-hover-row);
            }

            .model-item.selected {
                border-color: var(--accent-color);
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
                margin-left: auto;
                min-width: 0;
                overflow: hidden;
                text-overflow: ellipsis;
                white-space: nowrap;
                font-size: 0.75rem;
                color: var(--color-text-secondary);
                opacity: 0.8;
            }
        `,
    ],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class LlmModelItemComponent {
    @Input() config!: FullLLMConfig | FullRealtimeConfig;
    @Input() isSelected: boolean = false;

    @Output() selected = new EventEmitter<FullLLMConfig | FullRealtimeConfig>();

    onSelect(): void {
        this.selected.emit(this.config);
    }
}
