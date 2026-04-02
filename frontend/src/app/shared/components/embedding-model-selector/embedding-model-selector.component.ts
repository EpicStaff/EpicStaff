import { CommonModule } from '@angular/common';
import {
    ChangeDetectionStrategy,
    ChangeDetectorRef,
    Component,
    DestroyRef,
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

import { FullEmbeddingConfig } from '../../../features/settings-dialog/services/embeddings/full-embedding.service';
import { getProviderIconPath } from '../../../features/settings-dialog/utils/get-provider-icon';
import { DropdownManagerService } from '../../services/dropdown-manager.service';
import { AppIconComponent } from '../app-icon/app-icon.component';
import { EmbeddingModelItemComponent } from './embedding-model-item/embedding-model-item.component';

@Component({
    selector: 'app-embedding-model-selector',
    standalone: true,
    imports: [CommonModule, FormsModule, AppIconComponent, EmbeddingModelItemComponent],
    providers: [
        {
            provide: NG_VALUE_ACCESSOR,
            useExisting: forwardRef(() => EmbeddingModelSelectorComponent),
            multi: true,
        },
    ],
    template: `
        <div class="embedding-selector-container">
            <div class="selected-model" [class.placeholder]="!selectedConfig" (click)="toggleDropdown($event)">
                <div *ngIf="selectedConfig; else placeholderTemplate" class="model-info">
                    <app-icon
                        [icon]="getProviderIcon(selectedConfig)"
                        size="20px"
                        [ariaLabel]="selectedConfig.providerDetails?.name || ''"
                        class="provider-icon"
                    >
                    </app-icon>
                    <div class="model-text">
                        <span class="model-name">{{ selectedConfig.modelDetails?.name || 'Unknown Model' }}</span>
                        <span *ngIf="selectedConfig.custom_name" class="custom-name">
                            ({{ selectedConfig.custom_name }})
                        </span>
                    </div>
                </div>
                <ng-template #placeholderTemplate>
                    <div class="placeholder-text">{{ placeholder }}</div>
                </ng-template>
                <div class="dropdown-icon">
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
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
            <div class="dropdown-menu" [class.dropdown-top]="dropdownPosition === 'top'" *ngIf="isDropdownOpen">
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
                    <div *ngIf="filteredConfigs.length === 0" class="no-results">No matching models found</div>

                    @for (config of filteredConfigs; track config.id) {
                        <app-embedding-model-item
                            [config]="config"
                            [isSelected]="selectedConfigId === config.id"
                            (selected)="selectConfig($event)"
                        >
                        </app-embedding-model-item>
                    }
                </div>
            </div>
        </div>
    `,
    styles: [
        `
            .embedding-selector-container {
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

            .selected-model:hover {
                border-color: var(--accent-color);
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
                position: absolute;
                top: calc(100% + 4px);
                left: 0;
                width: 100%;
                background-color: var(--color-modals-background);
                border: 1px solid var(--color-divider-subtle);
                border-radius: 6px;
                box-shadow: 0 4px 12px rgba(0, 0, 0, 0.15);
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
export class EmbeddingModelSelectorComponent implements OnInit, OnDestroy, OnChanges, ControlValueAccessor {
    @Input() placeholder: string = 'Select embedding model';
    @Input() embeddingConfigs: FullEmbeddingConfig[] = [];

    @Output() modelSelected = new EventEmitter<number>();

    public isDropdownOpen = false;
    public searchTerm = '';
    public selectedConfigId: number | null = null;
    public selectedConfig: FullEmbeddingConfig | null = null;
    public filteredConfigs: FullEmbeddingConfig[] = [];
    public dropdownPosition: 'bottom' | 'top' = 'bottom';
    private dropdownId: string;

    // ControlValueAccessor implementation
    private onChange: (value: number | null) => void = () => {};
    private onTouched: () => void = () => {};
    private destroyRef = inject(DestroyRef);

    constructor(
        private cdr: ChangeDetectorRef,
        private dropdownManager: DropdownManagerService
    ) {
        // Generate unique ID for this dropdown instance
        this.dropdownId = `embedding-selector-${Math.random().toString(36).substr(2, 9)}`;
    }

    ngOnInit(): void {
        this.filteredConfigs = [...this.embeddingConfigs];
        this.updateSelectedConfig();

        // Subscribe to dropdown manager to close this dropdown when another opens
        this.dropdownManager.activeDropdown$.pipe(takeUntilDestroyed(this.destroyRef)).subscribe((activeId) => {
            if (activeId !== this.dropdownId && this.isDropdownOpen) {
                this.closeDropdown();
            }
        });
    }

    ngOnChanges(changes: SimpleChanges): void {
        if (changes['embeddingConfigs'] && this.embeddingConfigs) {
            this.filteredConfigs = [...this.embeddingConfigs];
            this.updateSelectedConfig();
            this.cdr.markForCheck();
        }
    }

    ngOnDestroy(): void {
        document.removeEventListener('click', this.closeDropdownOnClickOutside);
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
        this.isDropdownOpen = true;
        this.filterConfigs();
        this.checkDropdownPosition();

        // Notify dropdown manager that this dropdown is now active
        this.dropdownManager.openDropdown(this.dropdownId);

        // Add a one-time click listener to close when clicking outside
        setTimeout(() => {
            document.addEventListener('click', this.closeDropdownOnClickOutside);
        }, 100);

        this.cdr.markForCheck();
    }

    closeDropdownOnClickOutside = (event: MouseEvent): void => {
        const target = event.target as HTMLElement;
        const selectorEl = document.querySelector('.embedding-selector-container');

        if (selectorEl && !selectorEl.contains(target)) {
            this.closeDropdown();
            document.removeEventListener('click', this.closeDropdownOnClickOutside);
        }
    };

    closeDropdown(): void {
        this.isDropdownOpen = false;
        document.removeEventListener('click', this.closeDropdownOnClickOutside);

        // Notify dropdown manager that this dropdown is now closed
        this.dropdownManager.closeDropdown(this.dropdownId);

        this.cdr.markForCheck();
    }

    filterConfigs(): void {
        if (!this.searchTerm.trim()) {
            this.filteredConfigs = [...this.embeddingConfigs];
        } else {
            const searchTermLower = this.searchTerm.toLowerCase();
            this.filteredConfigs = this.embeddingConfigs.filter((config) => {
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

    selectConfig(config: FullEmbeddingConfig): void {
        this.selectedConfigId = config.id;
        this.selectedConfig = config;
        this.onChange(config.id);
        this.onTouched();
        this.modelSelected.emit(config.id);
        this.closeDropdown();
        document.removeEventListener('click', this.closeDropdownOnClickOutside);
    }

    getProviderIcon(config: FullEmbeddingConfig): string {
        if (!config || !config.providerDetails?.name) {
            return 'llm-providers-logos/default';
        }
        return getProviderIconPath(config.providerDetails.name);
    }

    // ControlValueAccessor implementation
    writeValue(value: number | null): void {
        this.selectedConfigId = value;

        if (value !== null && this.embeddingConfigs.length > 0) {
            this.selectedConfig = this.embeddingConfigs.find((config) => config.id === value) || null;
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
        if (this.selectedConfigId && this.embeddingConfigs.length > 0) {
            this.selectedConfig = this.embeddingConfigs.find((config) => config.id === this.selectedConfigId) || null;

            // if (this.selectedConfig) {
            //     console.log('Found selected config:', this.selectedConfig);
            // } else {
            //     console.log('No matching config found for ID:', this.selectedConfigId);
            // }

            this.cdr.markForCheck();
        }
    }

    // Check available space and position dropdown accordingly
    private checkDropdownPosition(): void {
        setTimeout(() => {
            const container = document.querySelector('.embedding-selector-container') as HTMLElement;
            if (!container) return;

            const rect = container.getBoundingClientRect();
            const viewportHeight = window.innerHeight;
            const dropdownHeight = 300; // max-height from CSS
            const spaceBelow = viewportHeight - rect.bottom;
            const spaceAbove = rect.top;

            // If there's not enough space below but enough space above, position on top
            if (spaceBelow < dropdownHeight && spaceAbove > dropdownHeight) {
                this.dropdownPosition = 'top';
            } else {
                this.dropdownPosition = 'bottom';
            }

            this.cdr.markForCheck();
        }, 0);
    }
}
