import { CommonModule } from '@angular/common';
import {
    ChangeDetectionStrategy,
    ChangeDetectorRef,
    Component,
    ElementRef,
    inject,
    OnDestroy,
    ViewEncapsulation,
} from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ICellRendererAngularComp } from 'ag-grid-angular';
import { ICellRendererParams } from 'ag-grid-community';

import { PromptConfig } from '../../../../../core/models/classification-decision-table.model';
import { MonacoCellRendererComponent } from '../monaco-cell-renderer/monaco-cell-renderer.component';

interface PromptTooltipParams extends ICellRendererParams {
    prompts: Record<string, PromptConfig>;
    onPromptChange: (promptId: string, field: keyof PromptConfig, value: PromptConfig[keyof PromptConfig]) => void;
}

@Component({
    selector: 'app-prompt-tooltip-renderer',
    standalone: true,
    imports: [CommonModule, FormsModule],
    template: `
        <div
            class="prompt-id-cell"
            (mouseenter)="showTooltip()"
            (mouseleave)="scheduleHide()"
            (mousedown)="removeTooltipNow()"
        >
            <span *ngIf="!value" class="placeholder select-placeholder">
                Select prompt <i class="ti ti-chevron-down"></i>
            </span>
            <ng-container *ngIf="value">
                <span *ngIf="!isDeleted" class="prompt-id-text">{{ value }}</span>
                <span *ngIf="isDeleted" class="deleted-prompt-badge">
                    <i class="ti ti-alert-triangle"></i> Deleted
                </span>
                <i *ngIf="hasPrompt" class="ti ti-eye prompt-indicator"></i>
            </ng-container>
        </div>
    `,
    styles: [
        `
            :host {
                display: block;
                width: 100%;
                height: 100%;
                position: absolute;
            }
            .prompt-id-cell {
                width: 100%;
                height: 100%;
                display: flex;
                align-items: center;
                padding: 0 8px;
                gap: 6px;
                cursor: default;
            }
            .prompt-id-text {
                color: #d4d4d4;
                white-space: nowrap;
                overflow: hidden;
                text-overflow: ellipsis;
                font-size: 14px;
            }
            .prompt-indicator {
                color: rgba(104, 95, 255, 0.6);
                font-size: 14px;
                flex-shrink: 0;
            }
            .select-placeholder {
                display: flex;
                align-items: center;
                gap: 4px;
                color: rgba(255, 255, 255, 0.35);
                font-size: 13px;
            }
            .select-placeholder .ti {
                font-size: 11px;
                opacity: 0.7;
            }
            .deleted-prompt-badge {
                display: inline-flex;
                align-items: center;
                gap: 4px;
                padding: 2px 8px;
                background: rgba(255, 59, 48, 0.15);
                color: var(--error-color, #ff3b30);
                border: 1px solid rgba(255, 59, 48, 0.35);
                border-radius: 10px;
                font-size: 11px;
                font-weight: 500;
                white-space: nowrap;
            }
            .deleted-prompt-badge .ti {
                font-size: 12px;
            }
        `,
    ],
    changeDetection: ChangeDetectionStrategy.OnPush,
    encapsulation: ViewEncapsulation.None,
})
export class PromptTooltipRendererComponent implements ICellRendererAngularComp, OnDestroy {
    private cdr = inject(ChangeDetectorRef);
    private elRef = inject(ElementRef);

    public value: string = '';
    public hasPrompt = false;
    public isDeleted = false;

    private params!: PromptTooltipParams;
    private tooltipEl: HTMLElement | null = null;
    private hideTimeout: ReturnType<typeof setTimeout> | null = null;
    private promptConfig: PromptConfig | null = null;
    private mouseInsideTooltip = false;
    private activeTextarea: HTMLTextAreaElement | null = null;
    private mouseGuard = (e: MouseEvent) => {
        if (this.activeTextarea && this.tooltipEl && !this.tooltipEl.contains(e.target as Node)) {
            // User clicked outside — close tooltip and let click through to new target
            this.removeTooltipNow();
        }
    };
    private focusReclaim = (e: FocusEvent) => {
        // If focus escapes to something outside the tooltip (not via click), reclaim it
        if (this.activeTextarea && this.tooltipEl && !this.tooltipEl.contains(e.target as Node)) {
            this.activeTextarea.focus();
        }
    };

    agInit(params: PromptTooltipParams): void {
        this.params = params;
        this.value = params.value || '';
        this.resolvePrompt();
    }

    refresh(params: PromptTooltipParams): boolean {
        this.params = params;
        this.value = params.value || '';
        this.resolvePrompt();
        this.cdr.markForCheck();
        return true;
    }

    ngOnDestroy(): void {
        this.removeTooltip();
        if (this.hideTimeout) clearTimeout(this.hideTimeout);
    }

    private resolvePrompt(): void {
        const prompts = this.params.prompts || {};
        this.promptConfig = this.value ? prompts[this.value] || null : null;
        this.hasPrompt = !!this.promptConfig;
        this.isDeleted = !!this.value && !this.promptConfig;
    }

    showTooltip(): void {
        if (this.hideTimeout) {
            clearTimeout(this.hideTimeout);
            this.hideTimeout = null;
        }

        if (!this.value || !this.hasPrompt) return;
        if (this.tooltipEl) return;
        // Close any active Monaco editor tooltip
        MonacoCellRendererComponent.closeActiveTooltip();

        this.resolvePrompt();
        if (!this.promptConfig) return;

        const tooltip = document.createElement('div');
        tooltip.className = 'prompt-tooltip-popover';
        tooltip.innerHTML = this.buildTooltipHTML(this.promptConfig);

        tooltip.addEventListener('mouseenter', () => {
            this.mouseInsideTooltip = true;
            if (this.hideTimeout) {
                clearTimeout(this.hideTimeout);
                this.hideTimeout = null;
            }
        });
        tooltip.addEventListener('mouseleave', () => {
            this.mouseInsideTooltip = false;
            this.scheduleHide();
        });
        tooltip.addEventListener('focusin', (e: FocusEvent) => {
            const target = e.target as HTMLElement;
            if (target?.tagName === 'TEXTAREA') {
                this.activeTextarea = target as HTMLTextAreaElement;
                document.addEventListener('mousedown', this.mouseGuard, true);
                document.addEventListener('focus', this.focusReclaim, true);
            }
        });
        tooltip.addEventListener('focusout', () => {
            setTimeout(() => {
                if (!this.tooltipEl?.contains(document.activeElement)) {
                    this.activeTextarea = null;
                    document.removeEventListener('mousedown', this.mouseGuard, true);
                    document.removeEventListener('focus', this.focusReclaim, true);
                    if (!this.mouseInsideTooltip) {
                        this.scheduleHide();
                    }
                }
            }, 0);
        });
        tooltip.addEventListener('keydown', (e: KeyboardEvent) => {
            if (e.key === 'Escape') {
                e.stopPropagation();
                this.removeTooltipNow();
            }
        });

        document.body.appendChild(tooltip);
        this.tooltipEl = tooltip;

        // Position relative to the cell
        const cellRect = this.elRef.nativeElement.getBoundingClientRect();
        const tooltipRect = tooltip.getBoundingClientRect();

        let left = cellRect.left;
        let top = cellRect.bottom + 4;

        // Keep within viewport
        if (left + tooltipRect.width > window.innerWidth - 16) {
            left = window.innerWidth - tooltipRect.width - 16;
        }
        if (top + tooltipRect.height > window.innerHeight - 16) {
            top = cellRect.top - tooltipRect.height - 4;
        }

        tooltip.style.left = `${left}px`;
        tooltip.style.top = `${top}px`;

        this.attachListeners(tooltip);
    }

    scheduleHide(): void {
        // Don't hide while a textarea inside the tooltip is focused
        if (this.tooltipEl?.contains(document.activeElement)) return;
        if (this.hideTimeout) clearTimeout(this.hideTimeout);
        this.hideTimeout = setTimeout(() => {
            this.removeTooltip();
        }, 200);
    }

    removeTooltipNow(): void {
        if (this.hideTimeout) {
            clearTimeout(this.hideTimeout);
            this.hideTimeout = null;
        }
        this.removeTooltip();
    }

    private removeTooltip(): void {
        if (this.tooltipEl) {
            this.activeTextarea = null;
            document.removeEventListener('mousedown', this.mouseGuard, true);
            document.removeEventListener('focus', this.focusReclaim, true);
            this.tooltipEl.remove();
            this.tooltipEl = null;
        }
    }

    private buildTooltipHTML(config: PromptConfig): string {
        const promptText = this.escapeHtml(config.prompt_text || '');
        const schemaText = this.escapeHtml(
            typeof config.output_schema === 'string'
                ? config.output_schema
                : JSON.stringify(config.output_schema, null, 2) || ''
        );
        const resultVar = this.escapeHtml(config.result_variable || '');

        return `
            <div class="ptp-header">
                <span class="ptp-title">${this.escapeHtml(this.value)}</span>
                ${resultVar ? `<span class="ptp-badge">→ ${resultVar}</span>` : ''}
            </div>
            <div class="ptp-field">
                <label class="ptp-label">Prompt Text</label>
                <textarea class="ptp-textarea ptp-prompt-text" rows="6" spellcheck="false">${promptText}</textarea>
            </div>
            <div class="ptp-field">
                <label class="ptp-label">Output Schema</label>
                <textarea class="ptp-textarea ptp-output-schema" rows="4" spellcheck="false">${schemaText}</textarea>
            </div>
        `;
    }

    private attachListeners(tooltip: HTMLElement): void {
        const promptTextarea = tooltip.querySelector('.ptp-prompt-text') as HTMLTextAreaElement;
        const schemaTextarea = tooltip.querySelector('.ptp-output-schema') as HTMLTextAreaElement;

        if (promptTextarea) {
            promptTextarea.addEventListener('input', () => {
                this.params.onPromptChange?.(this.value, 'prompt_text', promptTextarea.value);
            });
            // Prevent ag-grid from capturing key events inside textarea
            promptTextarea.addEventListener('keydown', (e) => e.stopPropagation());
        }

        if (schemaTextarea) {
            schemaTextarea.addEventListener('input', () => {
                const val = schemaTextarea.value;
                try {
                    const parsed = JSON.parse(val);
                    this.params.onPromptChange?.(this.value, 'output_schema', parsed);
                } catch {
                    this.params.onPromptChange?.(this.value, 'output_schema', val);
                }
            });
            schemaTextarea.addEventListener('keydown', (e) => e.stopPropagation());
        }
    }

    private escapeHtml(text: string): string {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }
}
