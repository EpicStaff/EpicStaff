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
                background: var(--graphite-900);
                border: 1px solid var(--graphite-750);
                border-radius: var(--radius-xl);
                box-shadow:
                    0px 2px 3px 0px var(--black-alpha-30),
                    0px 6px 10px 4px var(--black-alpha-15);
                padding: var(--space-xl);
                display: flex;
                flex-direction: column;
                gap: var(--space-lg);
                overflow: clip;
            }
            /* Search row */
            .pe-search-row {
                display: flex;
                gap: var(--space-sm);
                align-items: flex-start;
            }
            .pe-search-input {
                flex: 1;
                height: 40px;
                background: var(--graphite-750);
                color: var(--color-text-primary);
                border: 1px solid var(--fog-alpha-16);
                border-radius: var(--radius-sm);
                padding: 0 var(--space-lg);
                font-size: var(--font-size-md);
                font-family: var(--font-family-base);
                line-height: 1.3;
                outline: none;
                box-sizing: border-box;
            }
            .pe-search-input::placeholder {
                color: var(--color-text-secondary);
            }
            .pe-search-input:focus {
                border-color: var(--purple-alpha-50);
            }
            .pe-add-btn {
                width: 40px;
                height: 40px;
                flex-shrink: 0;
                background: var(--accent-color);
                border: none;
                border-radius: var(--radius-lg);
                color: var(--white);
                font-size: var(--font-size-xl);
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
                gap: var(--space-sm);
                max-height: 280px;
                overflow-y: auto;
            }
            .pe-item {
                height: 40px;
                background: var(--graphite-750);
                border: 1px solid var(--fog-alpha-16);
                border-radius: var(--radius-sm);
                padding: 0 var(--space-sm) 0 var(--space-lg);
                display: flex;
                align-items: center;
                justify-content: space-between;
                cursor: pointer;
                flex-shrink: 0;
            }
            .pe-item-selected {
                border-color: var(--purple-alpha-60);
                background: var(--purple-alpha-12);
            }
            .pe-item-left {
                display: flex;
                flex-direction: column;
                min-width: 0;
                flex: 1;
                overflow: hidden;
            }
            .pe-item-name {
                font-size: var(--font-size-md);
                font-family: var(--font-family-base);
                line-height: 1.3;
                color: var(--color-text-primary);
                white-space: nowrap;
                overflow: hidden;
                text-overflow: ellipsis;
            }
            .pe-item-var {
                font-size: var(--font-size-2xs);
                font-family: var(--font-family-base);
                line-height: 1.3;
                color: var(--color-text-secondary);
                white-space: nowrap;
                overflow: hidden;
                text-overflow: ellipsis;
            }
            .pe-item-right {
                display: flex;
                align-items: center;
                gap: var(--space-sm);
                flex-shrink: 0;
                margin-left: var(--space-sm);
            }
            .pe-item-llm {
                font-size: var(--font-size-md);
                font-family: var(--font-family-base);
                line-height: 1.3;
                color: var(--color-text-secondary);
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
                border-radius: var(--radius-sm);
                box-shadow: none;
                cursor: pointer;
                padding: 0;
                color: var(--accent-color);
                font-size: var(--font-size-lg);
            }
            .pe-item:hover .pe-item-open-btn {
                display: flex;
            }
            .pe-item-open-btn:hover {
                background: var(--purple-alpha-8);
            }
            /* Empty state */
            .pe-empty {
                display: flex;
                flex-direction: column;
                align-items: center;
                gap: var(--space-sm);
                padding: var(--space-2xl) 0;
                text-align: center;
            }
            .pe-empty-title {
                font-size: var(--font-size-md);
                font-family: var(--font-family-base);
                line-height: 1.3;
                color: var(--color-text-primary);
            }
            .pe-empty-hint {
                font-size: var(--font-size-xs);
                font-family: var(--font-family-base);
                line-height: 1.3;
                color: var(--color-text-secondary);
                max-width: 300px;
            }
            /* Clear */
            .pe-clear {
                display: inline-flex;
                align-items: center;
                justify-content: center;
                align-self: flex-start;
                padding: var(--space-xs) var(--space-lg);
                height: 32px;
                background: transparent;
                border: 1px solid var(--accent-color);
                border-radius: var(--radius-md);
                color: var(--accent-color);
                font-size: var(--font-size-md);
                font-family: var(--font-family-base);
                font-weight: var(--font-weight-regular);
                line-height: 1;
                cursor: pointer;
                box-shadow: none;
                transition: background 0.15s;
                box-sizing: border-box;
            }
            .pe-clear:hover {
                background: var(--purple-alpha-8);
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
