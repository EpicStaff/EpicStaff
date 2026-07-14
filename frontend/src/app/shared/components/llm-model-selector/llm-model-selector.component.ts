import { Dialog } from '@angular/cdk/dialog';
import { CommonModule } from '@angular/common';
import {
    ChangeDetectionStrategy,
    Component,
    computed,
    DestroyRef,
    EventEmitter,
    forwardRef,
    inject,
    Input,
    OnDestroy,
    OnInit,
    Output,
    signal,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { ControlValueAccessor, FormsModule, NG_VALUE_ACCESSOR } from '@angular/forms';
import { DropdownManagerService, FullLLMConfig, FullLLMConfigService } from '@shared/services';
import { getProviderIconPath } from '@shared/utils';

import { AppSvgIconComponent } from '../app-svg-icon/app-svg-icon.component';
import { LlmModelConfigDialogComponent } from '../llm-dialogs';
import { LlmModelItemComponent } from './llm-model-item/llm-model-item.component';

@Component({
    selector: 'app-llm-model-selector',
    standalone: true,
    imports: [CommonModule, FormsModule, AppSvgIconComponent, LlmModelItemComponent],
    providers: [
        {
            provide: NG_VALUE_ACCESSOR,
            useExisting: forwardRef(() => LlmModelSelectorComponent),
            multi: true,
        },
    ],
    template: `
        <div class="llm-selector-container">
            <div
                class="selected-model"
                [class.placeholder]="!selectedConfig()"
                [class.loading]="loading"
                (click)="!loading && toggleDropdown($event)"
            >
                @if (loading) {
                    <div class="loading-spinner"></div>
                }
                @if (selectedConfig() && !loading) {
                    <div class="model-info">
                        <app-svg-icon
                            [icon]="getProviderIcon(selectedConfig()!)"
                            size="20px"
                            [ariaLabel]="selectedConfig()!.providerDetails?.name || ''"
                            class="provider-icon"
                        />
                        <div class="model-text">
                            <span class="model-name">{{
                                selectedConfig()!.modelDetails?.name || 'Unknown Model'
                            }}</span>
                            @if (selectedConfig()!.custom_name) {
                                <span class="custom-name"> ({{ selectedConfig()!.custom_name }}) </span>
                            }
                        </div>
                    </div>
                } @else {
                    @if (!loading) {
                        <div class="placeholder-text">
                            {{ placeholder }}
                        </div>
                    }
                }
                <div class="dropdown-icon">
                    <svg
                        width="16"
                        height="16"
                        viewBox="0 0 24 24"
                        fill="none"
                        xmlns="http://www.w3.org/2000/svg"
                    >
                        <path
                            d="M6 9L12 15L18 9"
                            stroke="currentColor"
                            stroke-width="2"
                            stroke-linecap="round"
                            stroke-linejoin="round"
                        />
                    </svg>
                </div>
            </div>

            <!-- Dropdown Menu -->
            @if (isDropdownOpen()) {
                <div
                    class="dropdown-menu"
                    [class.dropdown-top]="dropdownPosition() === 'top'"
                >
                    <!-- Search Input -->
                    <div class="search-container">
                        <input
                            type="text"
                            [ngModel]="searchTerm()"
                            (ngModelChange)="searchTerm.set($event)"
                            placeholder="Search models..."
                            (click)="$event.stopPropagation()"
                        />
                        <button
                            class="create-btn"
                            (click)="onCreateLlm()"
                        >
                            Create LLM Model
                        </button>
                    </div>

                    <!-- Models List -->
                    <div class="models-list">
                        @if (selectedConfig() && !searchTerm()) {
                            <div
                                class="deselect-option"
                                (click)="deselectConfig()"
                            >
                                <i class="ti ti-x"></i>
                                <span>Clear</span>
                            </div>
                        }
                        @if (filteredConfigs().length === 0) {
                            <div class="no-results">No matching models found</div>
                        }

                        @for (config of filteredConfigs(); track config.id) {
                            <app-llm-model-item
                                [config]="config"
                                [isSelected]="selectedConfigId() === config.id"
                                (selected)="selectConfig($event)"
                            >
                            </app-llm-model-item>
                        }
                    </div>
                </div>
            }
        </div>
    `,
    styles: [
        `
            :host {
                width: 100%;
            }
            .llm-selector-container {
                position: relative;
                width: 100%;
            }

            .selected-model {
                display: flex;
                align-items: center;
                justify-content: space-between;
                background-color: var(--color-input-background);
                border: 1px solid var(--color-input-border);
                border-radius: var(--radius-md);
                padding: var(--space-md) var(--space-md);
                cursor: pointer;
                transition: border-color 0.2s ease;
                min-height: 42px;
            }

            .selected-model:hover:not(.loading) {
                border-color: var(--accent-color);
            }

            .selected-model.loading {
                cursor: default;
                opacity: 0.6;
            }

            .loading-spinner {
                width: 24px;
                height: 24px;
                border: 3px solid #44474f;
                border-top: 3px solid #b0b8c1;
                border-radius: 50%;
                animation: llm-spin 1s linear infinite;
                flex-shrink: 0;
            }

            @keyframes llm-spin {
                0% {
                    transform: rotate(0deg);
                }
                100% {
                    transform: rotate(360deg);
                }
            }

            .selected-model.placeholder {
                color: var(--white-alpha-30);
            }

            .model-info {
                display: flex;
                align-items: center;
                gap: var(--space-md);
                overflow: hidden;
                text-overflow: ellipsis;
                white-space: nowrap;
                flex: 1;
            }

            .provider-icon {
                flex-shrink: 0;
            }

            .model-text {
                display: flex;
                flex-direction: row;
                align-items: center;
                gap: var(--space-xs);
                overflow: hidden;
                text-overflow: ellipsis;
                white-space: nowrap;
            }

            .model-name {
                font-size: var(--font-size-md);
                color: var(--color-text-primary);
            }

            .custom-name {
                font-size: var(--font-size-xs);
                color: var(--color-text-secondary);
                opacity: 0.8;
            }

            .placeholder-text {
                color: var(--white-alpha-30);
                font-size: var(--font-size-md);
            }

            .dropdown-icon {
                margin-left: var(--space-sm);
                color: var(--color-text-secondary);
                transition: transform 0.2s ease;
            }

            .dropdown-menu {
                position: absolute;
                top: calc(100% + 4px);
                left: 0;
                width: 100%;
                background-color: var(--color-modals-background);
                border: 1px solid var(--color-divider-subtle);
                border-radius: var(--radius-md);
                box-shadow: 0 4px 12px var(--black-alpha-15);
                z-index: 1000;
                max-height: 300px;
                display: flex;
                flex-direction: column;
                overflow: hidden;
            }

            .dropdown-menu.dropdown-top {
                top: auto;
                bottom: calc(100% + 4px);
                flex-direction: column-reverse;
            }

            .dropdown-menu.dropdown-top .search-container {
                border-bottom: none;
                border-top: 1px solid var(--color-divider-subtle);
            }

            .search-container {
                display: flex;
                gap: var(--space-sm);
                padding: var(--space-xs) var(--space-sm);
                border-bottom: 1px solid var(--color-divider-subtle);
            }

            .search-container input {
                width: 100%;
                background-color: var(--color-input-background);
                border: 1px solid var(--color-input-border);
                border-radius: var(--radius-sm);
                padding: var(--space-xs) var(--space-md);
                color: var(--color-text-primary);
                font-size: var(--font-size-md);
                outline: none;
            }

            .search-container input:focus {
                border-color: var(--accent-color);
            }

            .search-container button {
                display: inline-flex;
                align-items: center;
                gap: var(--space-xs);
                background: var(--accent-color);
                color: var(--white);
                border: none;
                border-radius: var(--radius-md);
                padding: var(--space-xs) 0.85rem;
                font-size: var(--font-size-sm);
                font-weight: var(--font-weight-medium);
                cursor: pointer;
                white-space: nowrap;
                transition: background 0.2s ease;
            }

            .models-list {
                overflow-y: auto;
                max-height: 250px;
                padding: var(--space-2xs) var(--space-2xs) var(--space-sm) var(--space-2xs);
            }

            .deselect-option {
                display: flex;
                align-items: center;
                gap: var(--space-lg);
                padding: var(--space-sm) var(--space-md);
                cursor: pointer;
                font-size: var(--font-size-md);
                color: var(--color-text-secondary);
                border-bottom: 1px solid var(--color-divider-subtle);
                transition: background-color 0.15s ease;

                &:hover {
                    background-color: var(--white-alpha-5);
                    color: var(--color-text-primary);
                }

                i {
                    font-size: var(--font-size-lg);
                }
            }

            .no-results {
                padding: var(--space-md);
                text-align: center;
                color: var(--color-text-secondary);
                font-size: var(--font-size-md);
                font-style: italic;
            }
        `,
    ],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class LlmModelSelectorComponent implements OnInit, OnDestroy, ControlValueAccessor {
    @Input() placeholder: string = 'Select LLM model';
    @Input() loading: boolean = false;

    @Output() modelSelected = new EventEmitter<number>();

    private fullLLMConfigService = inject(FullLLMConfigService);
    private destroyRef = inject(DestroyRef);
    private dropdownManager = inject(DropdownManagerService);
    private dialog = inject(Dialog);

    public readonly llmConfigs = this.fullLLMConfigService.fullLLMConfigs;

    public searchTerm = signal('');
    public selectedConfigId = signal<number | null>(null);
    public isDropdownOpen = signal(false);
    public dropdownPosition = signal<'bottom' | 'top'>('top');

    public readonly selectedConfig = computed<FullLLMConfig | null>(() => {
        const id = this.selectedConfigId();
        if (id == null) return null;
        return this.llmConfigs().find((c) => c.id === id) ?? null;
    });

    public readonly filteredConfigs = computed<FullLLMConfig[]>(() => {
        const term = this.searchTerm().trim().toLowerCase();
        const configs = this.llmConfigs();
        if (!term) return [...configs];
        return configs.filter((config) => {
            const modelName = config.modelDetails?.name?.toLowerCase() || '';
            const customName = config.custom_name?.toLowerCase() || '';
            const providerName = config.providerDetails?.name?.toLowerCase() || '';
            return modelName.includes(term) || customName.includes(term) || providerName.includes(term);
        });
    });

    private dropdownId: string;

    // ControlValueAccessor implementation
    private onChange: (value: number | null) => void = () => {};
    private onTouched: () => void = () => {};

    constructor() {
        // Generate unique ID for this dropdown instance
        this.dropdownId = `llm-selector-${Math.random().toString(36).substr(2, 9)}`;

        this.fullLLMConfigService.getFullLLMConfigs().pipe(takeUntilDestroyed(this.destroyRef)).subscribe();
    }

    ngOnInit(): void {
        // Subscribe to dropdown manager to close this dropdown when another opens
        this.dropdownManager.activeDropdown$.pipe(takeUntilDestroyed(this.destroyRef)).subscribe((activeId) => {
            if (activeId !== this.dropdownId && this.isDropdownOpen()) {
                this.closeDropdown();
            }
        });
    }

    ngOnDestroy(): void {
        document.removeEventListener('click', this.closeDropdownOnClickOutside);
        if (this.isDropdownOpen()) {
            this.dropdownManager.closeDropdown(this.dropdownId);
            this.isDropdownOpen.set(false);
        }
    }

    toggleDropdown(event?: MouseEvent): void {
        if (event) {
            event.stopPropagation();
        }

        if (this.isDropdownOpen()) {
            this.closeDropdown();
        } else {
            this.openDropdown();
        }
    }

    private openDropdown(): void {
        this.isDropdownOpen.set(true);
        this.checkDropdownPosition();

        // Notify dropdown manager that this dropdown is now active
        this.dropdownManager.openDropdown(this.dropdownId);

        // Add a one-time click listener to close when clicking outside
        setTimeout(() => {
            document.addEventListener('click', this.closeDropdownOnClickOutside);
        }, 100);
    }

    closeDropdownOnClickOutside = (event: MouseEvent): void => {
        const target = event.target as HTMLElement;
        const selectorEl = document.querySelector('.llm-selector-container');

        if (selectorEl && !selectorEl.contains(target)) {
            this.closeDropdown();
            document.removeEventListener('click', this.closeDropdownOnClickOutside);
        }
    };

    closeDropdown(): void {
        this.isDropdownOpen.set(false);
        document.removeEventListener('click', this.closeDropdownOnClickOutside);

        // Notify dropdown manager that this dropdown is now closed
        this.dropdownManager.closeDropdown(this.dropdownId);
    }

    deselectConfig(): void {
        this.selectedConfigId.set(null);
        this.onChange(null);
        this.onTouched();
        this.modelSelected.emit(undefined);
        this.closeDropdown();
    }

    selectConfig(config: FullLLMConfig): void {
        this.selectedConfigId.set(config.id);
        this.onChange(config.id);
        this.onTouched();
        this.modelSelected.emit(config.id);
        this.closeDropdown();
        document.removeEventListener('click', this.closeDropdownOnClickOutside);
    }

    getProviderIcon(config: FullLLMConfig): string {
        if (!config || !config.providerDetails?.name) {
            return 'provider-default';
        }
        return getProviderIconPath(config.providerDetails.name);
    }

    onCreateLlm(): void {
        this.dialog.open(LlmModelConfigDialogComponent, {
            height: '90vh',
            width: '600px',
        });
    }

    // ControlValueAccessor implementation
    writeValue(value: number | null): void {
        this.selectedConfigId.set(value);
    }

    registerOnChange(fn: (value: number | null) => void): void {
        this.onChange = fn;
    }

    registerOnTouched(fn: () => void): void {
        this.onTouched = fn;
    }

    setDisabledState(isDisabled: boolean): void {
        void isDisabled;
    }

    // Check available space and position dropdown accordingly
    private checkDropdownPosition(): void {
        setTimeout(() => {
            const container = document.querySelector('.llm-selector-container') as HTMLElement;
            if (!container) return;

            const rect = container.getBoundingClientRect();
            const viewportHeight = window.innerHeight;
            const dropdownHeight = 300; // max-height from CSS
            const spaceBelow = viewportHeight - rect.bottom;
            const spaceAbove = rect.top;

            // If there's not enough space below but enough space above, position on top
            if (spaceBelow < dropdownHeight && spaceAbove > dropdownHeight) {
                this.dropdownPosition.set('top');
            } else {
                this.dropdownPosition.set('bottom');
            }
        }, 0);
    }
}
