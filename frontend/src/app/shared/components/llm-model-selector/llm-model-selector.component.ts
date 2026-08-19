import { Dialog } from '@angular/cdk/dialog';
import { ConnectedPosition, OverlayModule } from '@angular/cdk/overlay';
import { ComponentType } from '@angular/cdk/portal';
import {
    ChangeDetectionStrategy,
    Component,
    computed,
    DestroyRef,
    ElementRef,
    EventEmitter,
    forwardRef,
    inject,
    Input,
    input,
    OnDestroy,
    OnInit,
    Output,
    signal,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { ControlValueAccessor, FormsModule, NG_VALUE_ACCESSOR } from '@angular/forms';
import {
    DropdownManagerService,
    FullLLMConfig,
    FullLLMConfigService,
    FullRealtimeConfig,
    FullRealtimeConfigService,
} from '@shared/services';
import { getProviderIconPath } from '@shared/utils';
import { finalize, Observable } from 'rxjs';

import { AppSvgIconComponent } from '../app-svg-icon/app-svg-icon.component';
import { LlmModelConfigDialogComponent, VoiceModelConfigDialogComponent } from '../llm-dialogs';
import { LlmModelItemComponent } from './llm-model-item/llm-model-item.component';

export type ModelSelectorKind = 'llm' | 'realtime';
type SelectorConfig = FullLLMConfig | FullRealtimeConfig;

@Component({
    selector: 'app-llm-model-selector',
    imports: [FormsModule, OverlayModule, AppSvgIconComponent, LlmModelItemComponent],
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
                [class.placeholder]="!selectedConfig()"
                [class.loading]="isLoading"
                (click)="!isLoading && toggleDropdown($event)"
            >
                @if (isLoading) {
                    <div class="loading-spinner"></div>
                }
                @if (selectedConfig() && !isLoading) {
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
                    @if (!isLoading) {
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

            <!-- Dropdown Menu (rendered in an overlay so no parent overflow clips it) -->
            <ng-template
                cdkConnectedOverlay
                [cdkConnectedOverlayOrigin]="trigger"
                [cdkConnectedOverlayOpen]="isDropdownOpen()"
                [cdkConnectedOverlayWidth]="triggerWidth()"
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
                            [ngModel]="searchTerm()"
                            (ngModelChange)="searchTerm.set($event)"
                            placeholder="Search models..."
                            (click)="$event.stopPropagation()"
                        />
                        <button
                            class="create-btn"
                            (click)="onCreateLlm()"
                        >
                            {{ createButtonLabel() }}
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
                display: flex;
                gap: 8px;
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

            .search-container button {
                display: inline-flex;
                align-items: center;
                gap: 0.4rem;
                background: #685fff;
                color: #ffffff;
                border: none;
                border-radius: 6px;
                padding: 0.4rem 0.85rem;
                font-size: 0.82rem;
                font-weight: 500;
                cursor: pointer;
                white-space: nowrap;
                transition: background 0.2s ease;
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
export class LlmModelSelectorComponent implements OnInit, OnDestroy, ControlValueAccessor {
    @Input() placeholder: string = 'Select LLM model';
    @Input() loading: boolean = false;

    // Which pool of model configs to offer. Defaults to 'llm' so every existing
    // consumer keeps its current behaviour unchanged.
    readonly kind = input<ModelSelectorKind>('llm');

    @Output() modelSelected = new EventEmitter<number>();

    private readonly fullLLMConfigService = inject(FullLLMConfigService);
    private readonly fullRealtimeConfigService = inject(FullRealtimeConfigService);
    private readonly destroyRef = inject(DestroyRef);
    private readonly dropdownManager = inject(DropdownManagerService);
    private readonly dialog = inject(Dialog);
    private readonly elementRef = inject<ElementRef<HTMLElement>>(ElementRef);

    public readonly searchTerm = signal('');
    public readonly selectedConfigId = signal<number | null>(null);
    public readonly isDropdownOpen = signal(false);
    public readonly triggerWidth = signal(0);
    // Self-managed spinner during the selector's own initial pool load, OR'd with the
    // external `loading` input so consumers don't need to load the data just to drive it.
    private readonly configsLoading = signal(false);

    get isLoading(): boolean {
        return this.loading || this.configsLoading();
    }

    public readonly configs = computed<SelectorConfig[]>(() =>
        this.kind() === 'realtime'
            ? this.fullRealtimeConfigService.fullRealtimeConfigs()
            : this.fullLLMConfigService.fullLLMConfigs()
    );

    public readonly createButtonLabel = computed<string>(() =>
        this.kind() === 'realtime' ? 'Create Realtime Model' : 'Create LLM Model'
    );

    public readonly selectedConfig = computed<SelectorConfig | null>(() => {
        const id = this.selectedConfigId();
        if (id == null) return null;
        return this.configs().find((c) => c.id === id) ?? null;
    });

    public readonly filteredConfigs = computed<SelectorConfig[]>(() => {
        const term = this.searchTerm().trim().toLowerCase();
        const configs = this.configs();
        if (!term) return [...configs];
        return configs.filter((config) => {
            const modelName = config.modelDetails?.name?.toLowerCase() || '';
            const customName = config.custom_name?.toLowerCase() || '';
            const providerName = config.providerDetails?.name?.toLowerCase() || '';
            return modelName.includes(term) || customName.includes(term) || providerName.includes(term);
        });
    });

    // Prefer opening below the trigger; flip above when there isn't room.
    readonly overlayPositions: ConnectedPosition[] = [
        { originX: 'start', originY: 'bottom', overlayX: 'start', overlayY: 'top', offsetY: 4 },
        { originX: 'start', originY: 'top', overlayX: 'start', overlayY: 'bottom', offsetY: -4 },
    ];

    private readonly dropdownId: string;

    // ControlValueAccessor implementation
    private onChange: (value: number | null) => void = () => {};
    private onTouched: () => void = () => {};

    constructor() {
        // Generate unique ID for this dropdown instance
        this.dropdownId = `llm-selector-${Math.random().toString(36).substr(2, 9)}`;
    }

    ngOnInit(): void {
        // Load the pool matching this selector's kind. Both loaders are idempotent
        // (they hydrate root storage signals), so repeated instances are cheap.
        const load$: Observable<unknown> =
            this.kind() === 'realtime'
                ? this.fullRealtimeConfigService.getFullRealtimeConfigs()
                : this.fullLLMConfigService.getFullLLMConfigs();
        this.configsLoading.set(true);
        load$
            .pipe(
                finalize(() => this.configsLoading.set(false)),
                takeUntilDestroyed(this.destroyRef)
            )
            .subscribe();

        // Subscribe to dropdown manager to close this dropdown when another opens
        this.dropdownManager.activeDropdown$.pipe(takeUntilDestroyed(this.destroyRef)).subscribe((activeId) => {
            if (activeId !== this.dropdownId && this.isDropdownOpen()) {
                this.closeDropdown();
            }
        });
    }

    ngOnDestroy(): void {
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
        const container = this.elementRef.nativeElement.querySelector<HTMLElement>('.llm-selector-container');
        this.triggerWidth.set(container?.getBoundingClientRect().width ?? 0);

        this.isDropdownOpen.set(true);

        // Notify dropdown manager that this dropdown is now active
        this.dropdownManager.openDropdown(this.dropdownId);
    }

    onOverlayOutsideClick(event: MouseEvent): void {
        const container = this.elementRef.nativeElement.querySelector('.llm-selector-container');
        if (container && container.contains(event.target as Node)) return;
        this.closeDropdown();
    }

    closeDropdown(): void {
        if (!this.isDropdownOpen()) return;
        this.isDropdownOpen.set(false);

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

    selectConfig(config: SelectorConfig): void {
        this.selectedConfigId.set(config.id);
        this.onChange(config.id);
        this.onTouched();
        this.modelSelected.emit(config.id);
        this.closeDropdown();
    }

    getProviderIcon(config: SelectorConfig): string {
        if (!config || !config.providerDetails?.name) {
            return 'provider-default';
        }
        return getProviderIconPath(config.providerDetails.name);
    }

    onCreateLlm(): void {
        const component: ComponentType<unknown> =
            this.kind() === 'realtime' ? VoiceModelConfigDialogComponent : LlmModelConfigDialogComponent;
        this.dialog.open(component, {
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
}
