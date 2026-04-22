import { CommonModule } from '@angular/common';
import { AfterViewInit, ChangeDetectionStrategy, ChangeDetectorRef, Component, inject } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ICellEditorAngularComp } from 'ag-grid-angular';
import { ICellEditorParams } from 'ag-grid-community';

import { PromptConfig } from '../../../../../core/models/classification-decision-table.model';

interface LlmOption {
    id: number;
    label: string;
}

interface PromptIdEditorParams extends ICellEditorParams {
    prompts: Record<string, PromptConfig>;
    defaultLlmId: number | null;
    llmConfigs: LlmOption[];
    onAddPrompt: (id: string, config: PromptConfig) => void;
    onPromptChange: (promptId: string, field: keyof PromptConfig, value: PromptConfig[keyof PromptConfig]) => void;
}

@Component({
    selector: 'app-prompt-id-cell-editor',
    standalone: true,
    imports: [CommonModule, FormsModule],
    template: `
        <div class="prompt-editor-popup" (keydown)="onKeyDown($event)">
            <!-- Search / filter -->
            <div class="pe-search">
                <input
                    #searchInput
                    type="text"
                    class="pe-search-input"
                    [(ngModel)]="searchText"
                    (ngModelChange)="onSearchChange()"
                    placeholder="Search or type new ID..."
                    (keydown.enter)="onEnter()"
                    (keydown.escape)="cancel()"
                />
            </div>

            <!-- Existing prompts list -->
            <div class="pe-list" *ngIf="filteredPrompts.length > 0">
                <div *ngFor="let p of filteredPrompts" class="pe-item" [class.pe-item-selected]="p.id === value">
                    <div class="pe-item-main" (click)="selectPrompt(p.id)">
                        <span class="pe-item-id">{{ p.id }}</span>
                        <span class="pe-item-var" *ngIf="p.config.result_variable"
                            >→ {{ p.config.result_variable }}</span
                        >
                    </div>
                    <select
                        class="pe-llm-select"
                        [ngModel]="p.config.llm_config"
                        (ngModelChange)="onLlmChange(p.id, $event)"
                        (click)="$event.stopPropagation()"
                        title="LLM"
                    >
                        <option value="">Default LLM</option>
                        <option *ngFor="let llm of llmOptions" [value]="llm.id">{{ llm.label }}</option>
                    </select>
                </div>
            </div>

            <div class="pe-empty" *ngIf="filteredPrompts.length === 0 && !showNewForm">
                <span>No matching prompts</span>
            </div>

            <!-- Divider + Add new -->
            <div class="pe-divider"></div>

            <div *ngIf="!showNewForm" class="pe-add-btn" (click)="openNewForm()">
                <i class="ti ti-plus"></i> Add New Prompt
            </div>

            <!-- New prompt form -->
            <div *ngIf="showNewForm" class="pe-new-form">
                <div class="pe-field">
                    <label class="pe-label">Prompt ID</label>
                    <input
                        type="text"
                        class="pe-input"
                        [(ngModel)]="newId"
                        placeholder="e.g. classify_intent"
                        (keydown.escape)="showNewForm = false"
                    />
                </div>
                <div class="pe-field">
                    <label class="pe-label">Result Variable</label>
                    <input type="text" class="pe-input" [(ngModel)]="newResultVar" placeholder="e.g. classification" />
                </div>
                <div class="pe-field">
                    <label class="pe-label">Prompt Text</label>
                    <textarea
                        class="pe-textarea"
                        rows="5"
                        [(ngModel)]="newPromptText"
                        placeholder="Enter prompt template..."
                    ></textarea>
                </div>
                <div class="pe-field">
                    <label class="pe-label">Output Schema (JSON)</label>
                    <textarea
                        class="pe-textarea pe-schema"
                        rows="3"
                        [(ngModel)]="newSchema"
                        placeholder='{"key": "type"}'
                    ></textarea>
                </div>
                <div class="pe-field">
                    <label class="pe-label">LLM</label>
                    <select class="pe-select" [(ngModel)]="newLlmId">
                        <option value="">Default LLM</option>
                        <option *ngFor="let llm of llmOptions" [value]="llm.id">{{ llm.label }}</option>
                    </select>
                </div>
                <div class="pe-actions">
                    <button class="pe-btn pe-btn-cancel" (click)="showNewForm = false">Cancel</button>
                    <button class="pe-btn pe-btn-create" [disabled]="!newId.trim()" (click)="createPrompt()">
                        Create & Select
                    </button>
                </div>
            </div>

            <!-- Clear selection -->
            <div *ngIf="value" class="pe-clear" (click)="clearSelection()"><i class="ti ti-x"></i> Clear prompt</div>
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
                max-height: 480px;
                overflow-y: auto;
                background: #1e1e1e;
                border: 1px solid rgba(104, 95, 255, 0.4);
                border-radius: 8px;
                box-shadow: 0 8px 32px rgba(0, 0, 0, 0.5);
                padding: 8px 0;
                display: flex;
                flex-direction: column;
            }
            .pe-search {
                padding: 0 8px 6px;
            }
            .pe-search-input {
                width: 100%;
                background: #141414;
                color: #d4d4d4;
                border: 1px solid rgba(255, 255, 255, 0.1);
                border-radius: 6px;
                padding: 8px 10px;
                font-size: 13px;
                outline: none;
                box-sizing: border-box;
            }
            .pe-search-input:focus {
                border-color: rgba(104, 95, 255, 0.5);
            }
            .pe-list {
                max-height: 160px;
                overflow-y: auto;
            }
            .pe-item {
                display: flex;
                align-items: center;
                gap: 6px;
                padding: 5px 12px;
                transition: background 0.1s;
            }
            .pe-item:hover {
                background: rgba(104, 95, 255, 0.12);
            }
            .pe-item-selected {
                background: rgba(104, 95, 255, 0.2) !important;
                border-left: 2px solid #685fff;
            }
            .pe-item-main {
                display: flex;
                align-items: center;
                gap: 8px;
                flex: 1;
                cursor: pointer;
                min-width: 0;
            }
            .pe-item-id {
                font-family: 'Menlo', monospace;
                font-size: 13px;
                color: #e0e0e0;
                white-space: nowrap;
                overflow: hidden;
                text-overflow: ellipsis;
            }
            .pe-item-var {
                font-size: 11px;
                color: rgba(104, 95, 255, 0.8);
                margin-left: auto;
                white-space: nowrap;
            }
            .pe-llm-select {
                flex-shrink: 0;
                background: #141414;
                color: #a0a0a0;
                border: 1px solid rgba(255, 255, 255, 0.1);
                border-radius: 4px;
                padding: 2px 4px;
                font-size: 11px;
                outline: none;
                max-width: 120px;
                cursor: pointer;
            }
            .pe-llm-select:focus {
                border-color: rgba(104, 95, 255, 0.5);
            }
            .pe-select {
                width: 100%;
                background: #141414;
                color: #d4d4d4;
                border: 1px solid rgba(255, 255, 255, 0.1);
                border-radius: 5px;
                padding: 6px 8px;
                font-size: 13px;
                outline: none;
                box-sizing: border-box;
            }
            .pe-select:focus {
                border-color: rgba(104, 95, 255, 0.5);
            }
            .pe-empty {
                padding: 12px;
                text-align: center;
                color: rgba(255, 255, 255, 0.3);
                font-size: 12px;
            }
            .pe-divider {
                height: 1px;
                background: rgba(255, 255, 255, 0.08);
                margin: 4px 0;
            }
            .pe-add-btn {
                display: flex;
                align-items: center;
                gap: 6px;
                padding: 8px 12px;
                color: #685fff;
                font-size: 13px;
                cursor: pointer;
                transition: background 0.1s;
            }
            .pe-add-btn:hover {
                background: rgba(104, 95, 255, 0.08);
            }
            .pe-new-form {
                padding: 8px 12px;
                display: flex;
                flex-direction: column;
                gap: 8px;
            }
            .pe-field {
                display: flex;
                flex-direction: column;
                gap: 3px;
            }
            .pe-label {
                font-size: 11px;
                font-weight: 500;
                color: rgba(255, 255, 255, 0.5);
                text-transform: uppercase;
                letter-spacing: 0.4px;
            }
            .pe-input {
                width: 100%;
                background: #141414;
                color: #d4d4d4;
                border: 1px solid rgba(255, 255, 255, 0.1);
                border-radius: 5px;
                padding: 6px 8px;
                font-size: 13px;
                outline: none;
                box-sizing: border-box;
            }
            .pe-input:focus {
                border-color: rgba(104, 95, 255, 0.5);
            }
            .pe-textarea {
                width: 100%;
                background: #141414;
                color: #d4d4d4;
                border: 1px solid rgba(255, 255, 255, 0.1);
                border-radius: 5px;
                padding: 6px 8px;
                font-family: 'Menlo', monospace;
                font-size: 12px;
                line-height: 1.4;
                resize: vertical;
                outline: none;
                box-sizing: border-box;
            }
            .pe-textarea:focus {
                border-color: rgba(104, 95, 255, 0.5);
            }
            .pe-actions {
                display: flex;
                justify-content: flex-end;
                gap: 8px;
                padding-top: 4px;
            }
            .pe-btn {
                padding: 6px 14px;
                border: none;
                border-radius: 5px;
                font-size: 12px;
                cursor: pointer;
                font-weight: 500;
            }
            .pe-btn-cancel {
                background: rgba(255, 255, 255, 0.08);
                color: rgba(255, 255, 255, 0.6);
            }
            .pe-btn-cancel:hover {
                background: rgba(255, 255, 255, 0.12);
            }
            .pe-btn-create {
                background: #685fff;
                color: #fff;
            }
            .pe-btn-create:hover {
                background: #7a6fff;
            }
            .pe-btn-create:disabled {
                opacity: 0.4;
                cursor: not-allowed;
            }
            .pe-clear {
                display: flex;
                align-items: center;
                gap: 6px;
                padding: 6px 12px;
                color: #ff3b30;
                font-size: 12px;
                cursor: pointer;
                transition: background 0.1s;
            }
            .pe-clear:hover {
                background: rgba(255, 59, 48, 0.08);
            }
        `,
    ],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class PromptIdCellEditorComponent implements ICellEditorAngularComp, AfterViewInit {
    private cdr = inject(ChangeDetectorRef);
    private params!: PromptIdEditorParams;

    public value: string = '';
    public searchText: string = '';
    public showNewForm = false;

    // New prompt form fields
    public newId = '';
    public newResultVar = '';
    public newPromptText = '';
    public newSchema = '';
    public newLlmId: number | string | null = null;
    public llmOptions: LlmOption[] = [];

    private allPrompts: { id: string; config: PromptConfig }[] = [];
    public filteredPrompts: { id: string; config: PromptConfig }[] = [];

    agInit(params: PromptIdEditorParams): void {
        this.params = params;
        this.value = params.value || '';
        this.searchText = this.value;

        const prompts = params.prompts || {};
        this.allPrompts = Object.entries(prompts).map(([id, config]) => ({ id, config }));
        this.llmOptions = params.llmConfigs || [];
        this.newLlmId = params.defaultLlmId ?? null;
        this.filterPrompts();
    }

    ngAfterViewInit(): void {
        // Focus is handled by the search input autofocus
    }

    getValue(): string | null {
        return this.value || null;
    }

    isPopup(): boolean {
        return true;
    }

    getPopupPosition(): 'over' | 'under' | undefined {
        return 'under';
    }

    get filteredPromptsGetter() {
        return this.filteredPrompts;
    }

    selectPrompt(id: string): void {
        this.value = id;
        this.params.stopEditing(false);
    }

    clearSelection(): void {
        this.value = '';
        this.params.stopEditing(false);
    }

    openNewForm(): void {
        this.showNewForm = true;
        this.newId = this.searchText.trim();
        this.cdr.markForCheck();
    }

    createPrompt(): void {
        const id = this.newId.trim();
        if (!id) return;

        let schema: Record<string, string> | string = this.newSchema.trim();
        if (schema) {
            try {
                schema = JSON.parse(schema) as Record<string, string>;
            } catch {
                /* keep as string */
            }
        }

        const config: PromptConfig = {
            prompt_text: this.newPromptText,
            llm_config: (() => {
                const raw = this.newLlmId ?? this.params.defaultLlmId ?? null;
                if (raw === '' || raw == null) return null;
                const n = Number(raw);
                return Number.isFinite(n) ? n : null;
            })(),
            output_schema: schema || '',
            result_variable: this.newResultVar,
            variable_mappings: {},
        };

        this.params.onAddPrompt?.(id, config);
        this.value = id;
        this.params.stopEditing(false);
    }

    onEnter(): void {
        const search = this.searchText.trim();
        // If exact match exists, select it
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
        // Prevent ag-grid from capturing keys inside the popup
        event.stopPropagation();
    }

    // Called on searchText change via ngModel
    filterPrompts(): void {
        const q = (this.searchText || '').toLowerCase().trim();
        this.filteredPrompts = q ? this.allPrompts.filter((p) => p.id.toLowerCase().includes(q)) : [...this.allPrompts];
    }

    // Trigger filter when search changes
    onSearchChange(): void {
        this.filterPrompts();
        this.cdr.markForCheck();
    }

    onLlmChange(promptId: string, llmId: number | string | null | ''): void {
        const parsed = llmId === '' || llmId == null ? null : Number(llmId);
        const finalValue = Number.isFinite(parsed) ? parsed : null;
        this.params.onPromptChange?.(promptId, 'llm_config', finalValue);
    }
}
