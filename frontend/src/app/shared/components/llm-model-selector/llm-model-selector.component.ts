import { ConnectedPosition, OverlayModule } from '@angular/cdk/overlay';
import { CommonModule } from '@angular/common';
import {
    ChangeDetectionStrategy,
    ChangeDetectorRef,
    Component,
    DestroyRef,
    ElementRef,
    EventEmitter,
    forwardRef,
    inject,
    Input,
    OnChanges,
    OnDestroy,
    OnInit,
    Output,
    SimpleChanges,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { ControlValueAccessor, FormsModule, NG_VALUE_ACCESSOR } from '@angular/forms';
import { DropdownManagerService, FullLLMConfig } from '@shared/services';
import { getProviderIconPath } from '@shared/utils';

import { AppSvgIconComponent } from '../app-svg-icon/app-svg-icon.component';
import { LlmModelItemComponent } from './llm-model-item/llm-model-item.component';

@Component({
    selector: 'app-llm-model-selector',
    standalone: true,
    imports: [CommonModule, FormsModule, OverlayModule, AppSvgIconComponent, LlmModelItemComponent],
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
                #trigger="cdkOverlayOrigin"
                cdkOverlayOrigin
                class="selected-model"
                [class.placeholder]="!selectedConfig"
                [class.loading]="loading"
                (click)="!loading && toggleDropdown($event)"
            >
                <div
                    *ngIf="loading"
                    class="loading-spinner"
                ></div>
                <div
                    *ngIf="selectedConfig && !loading; else placeholderTemplate"
                    class="model-info"
                >
                    <app-svg-icon
                        [icon]="getProviderIcon(selectedConfig)"
                        size="20px"
                        [ariaLabel]="selectedConfig.providerDetails?.name || ''"
                        class="provider-icon"
                    />
                    <div class="model-text">
                        <span class="model-name">{{ selectedConfig.modelDetails?.name || 'Unknown Model' }}</span>
                        <span
                            *ngIf="selectedConfig.custom_name"
                            class="custom-name"
                        >
                            ({{ selectedConfig.custom_name }})
                        </span>
                    </div>
                </div>
                <ng-template #placeholderTemplate>
                    <div
                        *ngIf="!loading"
                        class="placeholder-text"
                    >
                        {{ placeholder }}
                    </div>
                </ng-template>
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

            <!-- Dropdown Menu (rendered in an overlay so no parent overflow clips it) -->
            <ng-template
                cdkConnectedOverlay
                [cdkConnectedOverlayOrigin]="trigger"
                [cdkConnectedOverlayOpen]="isDropdownOpen"
                [cdkConnectedOverlayWidth]="triggerWidth"
                [cdkConnectedOverlayPositions]="overlayPositions"
                [cdkConnectedOverlayFlexibleDimensions]="true"
                (overlayOutsideClick)="onOverlayOutsideClick($event)"
                (detach)="closeDropdown()"
            >
                <div class="dropdown-menu">
                    <!-- Search Input -->
                    <div class="search-container">
                        <input
                            type="text"
                            [(ngModel)]="searchTerm"
                            placeholder="Search models..."
                            (click)="$event.stopPropagation()"
                            (input)="filterConfigs()"
                        />
                    </div>

                    <!-- Models List -->
                    <div class="models-list">
                        @if (selectedConfig && !searchTerm) {
                            <div
                                class="deselect-option"
                                (click)="deselectConfig()"
                            >
                                <i class="ti ti-x"></i>
                                <span>Clear</span>
                            </div>
                        }
                        <div
                            *ngIf="filteredConfigs.length === 0"
                            class="no-results"
                        >
                            No matching models found
                        </div>

                        @for (config of filteredConfigs; track config.id) {
                            <app-llm-model-item
                                [config]="config"
                                [isSelected]="selectedConfigId === config.id"
                                (selected)="selectConfig($event)"
                            >
                            </app-llm-model-item>
                        }
                    </div>
                </div>
            </ng-template>
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
                border-radius: 6px;
                padding: 0.625rem 0.75rem;
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
                color: rgba(255, 255, 255, 0.3);
            }

            .model-info {
                display: flex;
                align-items: center;
                gap: 10px;
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
                font-size: 0.75rem;
                color: var(--color-text-secondary);
                opacity: 0.8;
            }

            .placeholder-text {
                color: rgba(255, 255, 255, 0.3);
                font-size: 0.875rem;
            }

            .dropdown-icon {
                margin-left: 8px;
                color: var(--color-text-secondary);
                transition: transform 0.2s ease;
            }

            .dropdown-menu {
                width: 100%;
                background-color: var(--color-modals-background);
                border: 1px solid var(--color-divider-subtle);
                border-radius: 6px;
                box-shadow: 0 4px 12px rgba(0, 0, 0, 0.15);
                max-height: 300px;
                display: flex;
                flex-direction: column;
                overflow: hidden;
            }

            .search-container {
                padding: 6px 8px;
                border-bottom: 1px solid var(--color-divider-subtle);
            }

            .search-container input {
                width: 100%;
                background-color: var(--color-input-background);
                border: 1px solid var(--color-input-border);
                border-radius: 4px;
                padding: 6px 10px;
                color: var(--color-text-primary);
                font-size: 0.875rem;
                outline: none;
            }

            .search-container input:focus {
                border-color: var(--accent-color);
            }

            .models-list {
                overflow-y: auto;
                max-height: 250px;
                padding: 4px 4px 8px 4px;
            }

            .deselect-option {
                display: flex;
                align-items: center;
                gap: 14px;
                padding: 8px 12px;
                cursor: pointer;
                font-size: 0.875rem;
                color: var(--color-text-secondary);
                border-bottom: 1px solid var(--color-divider-subtle);
                transition: background-color 0.15s ease;

                &:hover {
                    background-color: rgba(255, 255, 255, 0.05);
                    color: var(--color-text-primary);
                }

                i {
                    font-size: 16px;
                }
            }

            .no-results {
                padding: 12px;
                text-align: center;
                color: var(--color-text-secondary);
                font-size: 0.875rem;
                font-style: italic;
            }
        `,
    ],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class LlmModelSelectorComponent implements OnInit, OnDestroy, OnChanges, ControlValueAccessor {
    @Input() placeholder: string = 'Select LLM model';
    @Input() llmConfigs: FullLLMConfig[] = [];
    @Input() loading: boolean = false;

    @Output() modelSelected = new EventEmitter<number>();

    public isDropdownOpen = false;
    public searchTerm = '';
    public selectedConfigId: number | null = null;
    public selectedConfig: FullLLMConfig | null = null;
    public filteredConfigs: FullLLMConfig[] = [];
    public triggerWidth = 0;
    private dropdownId: string;

    // Prefer opening below the trigger; flip above when there isn't room.
    readonly overlayPositions: ConnectedPosition[] = [
        { originX: 'start', originY: 'bottom', overlayX: 'start', overlayY: 'top', offsetY: 4 },
        { originX: 'start', originY: 'top', overlayX: 'start', overlayY: 'bottom', offsetY: -4 },
    ];

    // ControlValueAccessor implementation
    private onChange: (value: number | null) => void = () => {};
    private onTouched: () => void = () => {};
    private destroyRef = inject(DestroyRef);

    constructor(
        private cdr: ChangeDetectorRef,
        private dropdownManager: DropdownManagerService,
        private elementRef: ElementRef<HTMLElement>
    ) {
        // Generate unique ID for this dropdown instance
        this.dropdownId = `llm-selector-${Math.random().toString(36).substr(2, 9)}`;
    }

    ngOnInit(): void {
        this.filteredConfigs = [...this.llmConfigs];
        this.updateSelectedConfig();

        // Subscribe to dropdown manager to close this dropdown when another opens
        this.dropdownManager.activeDropdown$.pipe(takeUntilDestroyed(this.destroyRef)).subscribe((activeId) => {
            if (activeId !== this.dropdownId && this.isDropdownOpen) {
                this.closeDropdown();
            }
        });
    }

    ngOnChanges(changes: SimpleChanges): void {
        if (changes['llmConfigs'] && this.llmConfigs) {
            this.filteredConfigs = [...this.llmConfigs];
            this.updateSelectedConfig();
            this.cdr.markForCheck();
        }
    }

    ngOnDestroy(): void {
        if (this.isDropdownOpen) {
            this.dropdownManager.closeDropdown(this.dropdownId);
            this.isDropdownOpen = false;
        }
    }

    toggleDropdown(event?: MouseEvent): void {
        if (event) {
            event.stopPropagation();
        }

        if (this.isDropdownOpen) {
            this.closeDropdown();
        } else {
            this.openDropdown();
        }
    }

    private openDropdown(): void {
        const container = this.elementRef.nativeElement.querySelector<HTMLElement>('.llm-selector-container');
        this.triggerWidth = container?.getBoundingClientRect().width ?? 0;

        this.isDropdownOpen = true;
        this.filterConfigs();

        // Notify dropdown manager that this dropdown is now active
        this.dropdownManager.openDropdown(this.dropdownId);

        this.cdr.markForCheck();
    }

    onOverlayOutsideClick(event: MouseEvent): void {
        const container = this.elementRef.nativeElement.querySelector('.llm-selector-container');
        if (container && container.contains(event.target as Node)) return;
        this.closeDropdown();
    }

    closeDropdown(): void {
        if (!this.isDropdownOpen) return;
        this.isDropdownOpen = false;

        // Notify dropdown manager that this dropdown is now closed
        this.dropdownManager.closeDropdown(this.dropdownId);

        this.cdr.markForCheck();
    }

    filterConfigs(): void {
        if (!this.searchTerm.trim()) {
            this.filteredConfigs = [...this.llmConfigs];
        } else {
            const searchTermLower = this.searchTerm.toLowerCase();
            this.filteredConfigs = this.llmConfigs.filter((config) => {
                const modelName = config.modelDetails?.name?.toLowerCase() || '';
                const customName = config.custom_name?.toLowerCase() || '';
                const providerName = config.providerDetails?.name?.toLowerCase() || '';

                return (
                    modelName.includes(searchTermLower) ||
                    customName.includes(searchTermLower) ||
                    providerName.includes(searchTermLower)
                );
            });
        }
        this.cdr.markForCheck();
    }

    deselectConfig(): void {
        this.selectedConfigId = null;
        this.selectedConfig = null;
        this.onChange(null);
        this.onTouched();
        this.modelSelected.emit(undefined);
        this.closeDropdown();
    }

    selectConfig(config: FullLLMConfig): void {
        this.selectedConfigId = config.id;
        this.selectedConfig = config;
        this.onChange(config.id);
        this.onTouched();
        this.modelSelected.emit(config.id);
        this.closeDropdown();
    }

    getProviderIcon(config: FullLLMConfig): string {
        if (!config || !config.providerDetails?.name) {
            return 'provider-default';
        }
        return getProviderIconPath(config.providerDetails.name);
    }

    // ControlValueAccessor implementation
    writeValue(value: number | null): void {
        this.selectedConfigId = value;

        if (value !== null && this.llmConfigs.length > 0) {
            this.selectedConfig = this.llmConfigs.find((config) => config.id === value) || null;
        } else {
            this.selectedConfig = null;
        }

        this.cdr.markForCheck();
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

    // Add this helper method to update the selected config
    private updateSelectedConfig(): void {
        if (this.selectedConfigId && this.llmConfigs.length > 0) {
            this.selectedConfig = this.llmConfigs.find((config) => config.id === this.selectedConfigId) || null;

            this.cdr.markForCheck();
        }
    }
}
