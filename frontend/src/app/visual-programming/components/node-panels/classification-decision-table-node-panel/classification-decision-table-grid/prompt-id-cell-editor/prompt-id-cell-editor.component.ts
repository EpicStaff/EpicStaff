import { CommonModule } from '@angular/common';
import { AfterViewInit, ChangeDetectionStrategy, ChangeDetectorRef, Component, inject } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ICellEditorParams } from 'ag-grid-community';

import { PromptConfig } from '../../../../../core/models/classification-decision-table.model';
import { resolveLlmLabel } from '../../cdt-llm-label.util';
import { filterByQuery } from '../../cdt-search-filter.util';
import { BaseCellEditor } from '../shared/base-cell-editor';

interface LlmOption {
    id: number;
    label: string;
}

interface PromptIdEditorParams extends ICellEditorParams {
    prompts: Record<string, PromptConfig>;
    defaultLlmId: number | null;
    llmConfigs: LlmOption[];
    onNavigateToPrompts: () => void;
    onOpenPromptForEdit: (promptId: string) => void;
}

@Component({
    selector: 'app-prompt-id-cell-editor',
    imports: [CommonModule, FormsModule],
    template: `
        <div
            class="prompt-editor-popup"
            (keydown)="onKeyDown($event)"
        >
            <!-- Search row: input + "+" button -->
            <div class="pe-search-row">
                <input
                    #searchInput
                    type="text"
                    class="pe-search-input"
                    [ngModel]="searchText"
                    (ngModelChange)="onSearchChange($event)"
                    placeholder="Search prompt..."
                    autofocus
                    (keydown.enter)="onEnter()"
                    (keydown.escape)="cancel()"
                />
                <button
                    class="pe-add-btn"
                    type="button"
                    title="Navigate to Prompt Library"
                    (click)="navigateToPrompts()"
                >
                    <i class="ti ti-plus"></i>
                </button>
            </div>

            <!-- Options list -->
            <div
                class="pe-list"
                *ngIf="filteredPrompts.length > 0"
            >
                <div
                    *ngFor="let p of filteredPrompts"
                    class="pe-item"
                    [class.pe-item-selected]="p.id === value"
                    (click)="selectPrompt(p.id)"
                >
                    <div class="pe-item-left">
                        <span class="pe-item-name">{{ p.id }}</span>
                        <span
                            class="pe-item-var"
                            *ngIf="p.config.result_variable"
                            >{{ p.config.result_variable }}</span
                        >
                    </div>
                    <div class="pe-item-right">
                        <span class="pe-item-llm">{{ resolveLlmLabel(p.config.llm_config) }}</span>
                        <button
                            class="pe-item-open-btn"
                            type="button"
                            title="Open in Prompt Library"
                            (click)="openPromptForEdit(p.id, $event)"
                        >
                            <i class="ti ti-arrow-up-right"></i>
                        </button>
                    </div>
                </div>
            </div>

            <!-- Empty state -->
            <div
                class="pe-empty"
                *ngIf="filteredPrompts.length === 0"
            >
                <span class="pe-empty-title">Prompt not found</span>
                <span class="pe-empty-hint"
                    >You can enter a different name for the prompt or click "+" to create a new one</span
                >
            </div>

            <!-- Clear selection -->
            <button
                *ngIf="value"
                type="button"
                class="pe-clear"
                (click)="clearSelection()"
            >
                Clear
            </button>
        </div>
    `,
    styles: [
        `
            :host {
                display: block;
                position: absolute;
            }
            .prompt-editor-popup {
                width: 380px;
                background: #212325;
                border: 1px solid #2b2d30;
                border-radius: 10px;
                box-shadow:
                    0px 2px 3px 0px rgba(0, 0, 0, 0.3),
                    0px 6px 10px 4px rgba(0, 0, 0, 0.15);
                padding: 20px;
                display: flex;
                flex-direction: column;
                gap: 16px;
                overflow: clip;
            }
            /* Search row */
            .pe-search-row {
                display: flex;
                gap: 8px;
                align-items: flex-start;
            }
            .pe-search-input {
                flex: 1;
                height: 40px;
                background: #2b2d30;
                color: var(--color-text-primary);
                border: 1px solid rgba(217, 217, 222, 0.16);
                border-radius: 4px;
                padding: 0 16px;
                font-size: 14px;
                font-family: Inter, sans-serif;
                line-height: 1.3;
                outline: none;
                box-sizing: border-box;
            }
            .pe-search-input::placeholder {
                color: rgba(217, 217, 222, 0.6);
            }
            .pe-search-input:focus {
                border-color: rgba(104, 95, 255, 0.5);
            }
            .pe-add-btn {
                width: 40px;
                height: 40px;
                flex-shrink: 0;
                background: var(--accent-color);
                border: none;
                border-radius: 8px;
                color: #fff;
                font-size: 18px;
                display: flex;
                align-items: center;
                justify-content: center;
                cursor: pointer;
                padding: 0;
                transition: opacity 0.15s;
            }
            .pe-add-btn:hover {
                opacity: 0.85;
            }
            /* Options list */
            .pe-list {
                display: flex;
                flex-direction: column;
                gap: 8px;
                max-height: 280px;
                overflow-y: auto;
            }
            .pe-item {
                height: 40px;
                background: #2b2d30;
                border: 1px solid rgba(217, 217, 222, 0.16);
                border-radius: 4px;
                padding: 0 8px 0 16px;
                display: flex;
                align-items: center;
                justify-content: space-between;
                cursor: pointer;
                flex-shrink: 0;
            }
            .pe-item-selected {
                border-color: rgba(104, 95, 255, 0.6);
                background: rgba(104, 95, 255, 0.12);
            }
            .pe-item-left {
                display: flex;
                flex-direction: column;
                min-width: 0;
                flex: 1;
                overflow: hidden;
            }
            .pe-item-name {
                font-size: 14px;
                font-family: Inter, sans-serif;
                line-height: 1.3;
                color: var(--color-text-primary);
                white-space: nowrap;
                overflow: hidden;
                text-overflow: ellipsis;
            }
            .pe-item-var {
                font-size: 10px;
                font-family: Inter, sans-serif;
                line-height: 1.3;
                color: rgba(217, 217, 222, 0.6);
                white-space: nowrap;
                overflow: hidden;
                text-overflow: ellipsis;
            }
            .pe-item-right {
                display: flex;
                align-items: center;
                gap: 8px;
                flex-shrink: 0;
                margin-left: 8px;
            }
            .pe-item-llm {
                font-size: 14px;
                font-family: Inter, sans-serif;
                line-height: 1.3;
                color: rgba(217, 217, 222, 0.6);
                white-space: nowrap;
                max-width: 180px;
                overflow: hidden;
                text-overflow: ellipsis;
            }
            .pe-item-open-btn {
                display: none;
                align-items: center;
                justify-content: center;
                width: 28px;
                height: 28px;
                flex-shrink: 0;
                background: transparent;
                border: 1px solid var(--accent-color);
                border-radius: 4px;
                box-shadow: none;
                cursor: pointer;
                padding: 0;
                color: var(--accent-color);
                font-size: 16px;
            }
            .pe-item:hover .pe-item-open-btn {
                display: flex;
            }
            .pe-item-open-btn:hover {
                background: rgba(104, 95, 255, 0.08);
            }
            /* Empty state */
            .pe-empty {
                display: flex;
                flex-direction: column;
                align-items: center;
                gap: 8px;
                padding: 24px 0;
                text-align: center;
            }
            .pe-empty-title {
                font-size: 14px;
                font-family: Inter, sans-serif;
                line-height: 1.3;
                color: var(--color-text-primary);
            }
            .pe-empty-hint {
                font-size: 12px;
                font-family: Inter, sans-serif;
                line-height: 1.3;
                color: rgba(217, 217, 222, 0.6);
                max-width: 300px;
            }
            /* Clear */
            .pe-clear {
                display: inline-flex;
                align-items: center;
                justify-content: center;
                align-self: flex-start;
                padding: 6px 16px;
                height: 32px;
                background: transparent;
                border: 1px solid var(--accent-color);
                border-radius: 6px;
                color: var(--accent-color);
                font-size: 14px;
                font-family: Inter, sans-serif;
                font-weight: 400;
                line-height: 1;
                cursor: pointer;
                box-shadow: none;
                transition: background 0.15s;
                box-sizing: border-box;
            }
            .pe-clear:hover {
                background: rgba(104, 95, 255, 0.08);
            }
        `,
    ],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class PromptIdCellEditorComponent extends BaseCellEditor<PromptIdEditorParams> implements AfterViewInit {
    private cdr = inject(ChangeDetectorRef);

    public value: string = '';
    public searchText: string = '';
    public llmOptions: LlmOption[] = [];

    private allPrompts: { id: string; config: PromptConfig }[] = [];
    public filteredPrompts: { id: string; config: PromptConfig }[] = [];

    override agInit(params: PromptIdEditorParams): void {
        super.agInit(params);
        this.value = params.value || '';
        this.searchText = '';

        const prompts = params.prompts || {};
        this.allPrompts = Object.entries(prompts).map(([id, config]) => ({ id, config }));
        this.llmOptions = params.llmConfigs || [];
        this.filterPrompts();
    }

    ngAfterViewInit(): void {
        // Focus handled by autofocus on the search input
    }

    getValue(): string | null {
        return this.value || null;
    }

    getPopupPosition(): 'over' | 'under' | undefined {
        return 'under';
    }

    selectPrompt(id: string): void {
        this.value = id;
        this.params.stopEditing(false);
    }

    clearSelection(): void {
        this.value = '';
        this.params.stopEditing(false);
    }

    navigateToPrompts(): void {
        this.params.onNavigateToPrompts?.();
        this.params.stopEditing(true);
    }

    openPromptForEdit(promptId: string, event: MouseEvent): void {
        event.stopPropagation();
        this.params.onOpenPromptForEdit?.(promptId);
        this.params.stopEditing(true);
    }

    onEnter(): void {
        const search = this.searchText.trim();
        const match = this.allPrompts.find((p) => p.id === search);
        if (match) {
            this.selectPrompt(match.id);
        } else if (this.filteredPrompts.length === 1) {
            this.selectPrompt(this.filteredPrompts[0].id);
        }
    }

    cancel(): void {
        this.params.stopEditing(true);
    }

    onKeyDown(event: KeyboardEvent): void {
        event.stopPropagation();
    }

    filterPrompts(): void {
        const q = (this.searchText || '').trim();
        this.filteredPrompts = filterByQuery(this.allPrompts, q, (p) => p.id);
    }

    onSearchChange(value: string): void {
        this.searchText = value;
        this.filterPrompts();
        this.cdr.markForCheck();
    }

    resolveLlmLabel(llmId: number | null | undefined): string {
        return resolveLlmLabel(llmId, this.llmOptions);
    }
}
