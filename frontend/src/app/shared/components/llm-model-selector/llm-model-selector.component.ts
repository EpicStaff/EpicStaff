import { CdkTrapFocus } from '@angular/cdk/a11y';
import { Dialog } from '@angular/cdk/dialog';
import { ConnectedPosition, OverlayModule } from '@angular/cdk/overlay';
import { NgTemplateOutlet } from '@angular/common';
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
import { MatTooltip } from '@angular/material/tooltip';
import { HasPermissionDirective } from '@shared/directives';
import { ActionCode, ResourceCode } from '@shared/models';
import {
    DropdownManagerService,
    FullLLMConfig,
    FullLLMConfigService,
    FullRealtimeConfig,
    FullRealtimeConfigService,
} from '@shared/services';
import { getProviderIconPath, providerDisplayName } from '@shared/utils';
import { finalize, Observable } from 'rxjs';

import { AppSvgIconComponent } from '../app-svg-icon/app-svg-icon.component';
import { ButtonComponent } from '../buttons/button/button.component';
import { ModelConfigDialogComponent, ModelConfigDialogData, VoiceModelConfigDialogComponent } from '../llm-dialogs';
import { LlmModelItemComponent } from './llm-model-item/llm-model-item.component';

export type ModelSelectorKind = 'llm' | 'realtime';
type SelectorConfig = FullLLMConfig | FullRealtimeConfig;

/** Search row + "Create LLM Model" need more room than a narrow trigger (e.g. side-by-side fallbacks). */
const PANEL_MIN_WIDTH_PX = 280;

@Component({
    selector: 'app-llm-model-selector',
    imports: [
        FormsModule,
        OverlayModule,
        CdkTrapFocus,
        AppSvgIconComponent,
        ButtonComponent,
        LlmModelItemComponent,
        HasPermissionDirective,
        MatTooltip,
        NgTemplateOutlet,
    ],
    providers: [
        {
            provide: NG_VALUE_ACCESSOR,
            useExisting: forwardRef(() => LlmModelSelectorComponent),
            multi: true,
        },
    ],
    template: `
        <div class="llm-selector-container">
            @if (readonly()) {
                <!-- Read-only: the value as plain text, nothing to open. -->
                <div
                    class="selected-model readonly"
                    [class.placeholder]="!selectedConfig()"
                    [class.loading]="isLoading"
                >
                    <ng-container *ngTemplateOutlet="selectedModel" />
                </div>
            } @else {
                <button
                    type="button"
                    #trigger="cdkOverlayOrigin"
                    cdkOverlayOrigin
                    class="selected-model"
                    [class.placeholder]="!selectedConfig()"
                    [class.loading]="isLoading"
                    [class.open]="isDropdownOpen()"
                    [disabled]="isLoading"
                    [attr.aria-expanded]="isDropdownOpen()"
                    [matTooltip]="placeholder"
                    (click)="toggleDropdown($event)"
                >
                    <ng-container *ngTemplateOutlet="selectedModel" />
                    <span
                        class="dropdown-icon"
                        [class.open]="isDropdownOpen()"
                    >
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
                    </span>
                </button>

                <!-- Dropdown Menu (rendered in an overlay so no parent overflow clips it) -->
                <ng-template
                    cdkConnectedOverlay
                    [cdkConnectedOverlayOrigin]="trigger"
                    [cdkConnectedOverlayOpen]="isDropdownOpen()"
                    [cdkConnectedOverlayWidth]="overlayWidth()"
                    [cdkConnectedOverlayMinWidth]="panelMinWidthPx"
                    [cdkConnectedOverlayPositions]="overlayPositions"
                    [cdkConnectedOverlayFlexibleDimensions]="true"
                    [cdkConnectedOverlayPush]="true"
                    [cdkConnectedOverlayViewportMargin]="8"
                    (overlayOutsideClick)="onOverlayOutsideClick($event)"
                    (detach)="closeDropdown()"
                >
                    <div
                        class="dropdown-menu"
                        cdkTrapFocus
                        [cdkTrapFocusAutoCapture]="true"
                    >
                        <!-- Search Input -->
                        <div class="search-container">
                            <input
                                type="text"
                                [ngModel]="searchTerm()"
                                [ngModelOptions]="{ standalone: true }"
                                (ngModelChange)="searchTerm.set($event)"
                                placeholder="Search models..."
                                aria-label="Search models"
                                (click)="$event.stopPropagation()"
                            />
                            <button
                                *appHasPermission="[ResourceCode.LlmConfigs, ActionCode.Create]"
                                type="button"
                                class="create-btn"
                                [attr.aria-label]="createButtonLabel()"
                                [matTooltip]="createButtonLabel()"
                                (click)="onCreateLlm()"
                            >
                                +
                            </button>
                        </div>

                        <!-- Models List -->
                        <div class="models-list">
                            @if (filteredConfigs().length === 0) {
                                <div class="no-results">No matching models found</div>
                            }

                            @for (group of groupedConfigs(); track group.provider) {
                                <div class="provider-group-label">
                                    <app-svg-icon
                                        [icon]="getProviderIcon(group.configs[0])"
                                        size="20px"
                                    />
                                    <span>{{ providerName(group.provider) }}</span>
                                </div>
                                @for (config of group.configs; track config.id) {
                                    <app-llm-model-item
                                        [config]="config"
                                        [isSelected]="selectedConfigId() === config.id"
                                        (selected)="selectConfig($event)"
                                    >
                                    </app-llm-model-item>
                                }
                            }
                        </div>

                        <div class="dropdown-footer">
                            <app-button
                                type="outline-primary"
                                [disabled]="!selectedConfig()"
                                (click)="deselectConfig()"
                                >Clear</app-button
                            >
                        </div>
                    </div>
                </ng-template>
            }
        </div>

        <ng-template #selectedModel>
            @if (isLoading) {
                <span class="loading-spinner"></span>
            }
            @if (selectedConfig() && !isLoading) {
                <span class="model-info">
                    <app-svg-icon
                        [icon]="getProviderIcon(selectedConfig()!)"
                        size="20px"
                        [ariaLabel]="selectedConfig()!.providerDetails?.name || ''"
                        class="provider-icon"
                    />
                    <span class="model-text">
                        <span class="model-name">{{ selectedConfig()!.modelDetails?.name || 'Unknown Model' }}</span>
                        @if (selectedConfig()!.custom_name) {
                            <span class="custom-name"> ({{ selectedConfig()!.custom_name }}) </span>
                        }
                    </span>
                </span>
            } @else {
                @if (!isLoading) {
                    <span class="placeholder-text">
                        {{ placeholder }}
                    </span>
                }
            }
        </ng-template>
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
                position: relative;
                display: flex;
                align-items: center;
                gap: 0.5rem;
                height: 40px;
                background-color: var(--color-input-background);
                border: 1px solid var(--color-input-border);
                border-radius: 4px;
                padding: 0.5rem 2rem 0.5rem 1rem;
                font-size: 0.875rem;
                line-height: var(--text-body-line-height);
                cursor: pointer;
                transition: border-color 0.2s ease;
                width: 100%;
                color: inherit;
                font-family: inherit;
                text-align: left;
            }

            .selected-model:is(:hover, :focus-visible):not(.loading):not(.readonly),
            .selected-model.open:not(.readonly) {
                border-color: var(--accent-color);
            }

            .selected-model.loading {
                cursor: default;
                opacity: 0.6;
            }

            .selected-model.readonly {
                cursor: default;
                background-color: transparent;
                border-color: transparent;
                padding-left: 0;
                padding-right: 0;
            }

            .loading-spinner {
                display: block;
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
                color: var(--color-input-text-placeholder);
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
                display: block;
                flex: 1;
                min-width: 0;
                overflow: hidden;
                text-overflow: ellipsis;
                white-space: nowrap;
                color: var(--color-input-text-placeholder);
            }

            .dropdown-icon {
                position: absolute;
                top: 50%;
                right: 10px;
                display: flex;
                color: var(--color-input-text-placeholder);
                transform: translateY(-50%);
                transition: transform 0.2s ease;
            }

            .dropdown-icon.open {
                transform: translateY(-50%) rotate(180deg);
            }

            .dropdown-menu {
                width: 100%;
                background-color: var(--color-sidenav-background);
                border: 1px solid var(--color-divider-subtle);
                border-radius: 8px;
                box-shadow: 0 4px 12px rgba(0, 0, 0, 0.15);
                max-height: 400px;
                display: flex;
                flex-direction: column;
                gap: 1rem;
                padding: 1rem;
                overflow: hidden;
            }

            .search-container {
                display: flex;
                gap: 0.5rem;
                flex-shrink: 0;
            }

            .search-container input {
                flex: 1;
                min-width: 0;
                height: 40px;
                background-color: var(--color-ks-line);
                border: 1px solid var(--color-input-border);
                border-radius: 4px;
                padding: 0 0.75rem;
                color: var(--color-text-primary);
                font-size: 0.875rem;
                outline: none;
            }

            .search-container input:focus {
                border-color: var(--accent-color);
            }

            .search-container button {
                flex-shrink: 0;
                width: 40px;
                height: 40px;
                display: inline-flex;
                align-items: center;
                justify-content: center;
                background: var(--purple-primary);
                color: var(--white);
                border: none;
                border-radius: 8px;
                font-size: 1.125rem;
                line-height: 1;
                cursor: pointer;
                transition: opacity 0.15s ease;
            }

            .search-container button:hover {
                opacity: 0.8;
            }

            .models-list {
                display: flex;
                flex-direction: column;
                gap: 0.5rem;
                overflow-y: auto;
                flex: 1;
                min-height: 0;
                scrollbar-gutter: stable;
            }

            .provider-group-label {
                display: flex;
                align-items: center;
                gap: 0.5rem;
                flex-shrink: 0;
                padding: 0.25rem 0;
                font-size: 0.875rem;
                color: var(--color-text-secondary);
            }

            .dropdown-footer {
                display: flex;
                flex-shrink: 0;
                margin: 0 -1rem -1rem;
                padding: 10px 1rem;
                border-top: 1px solid var(--color-divider-subtle);
                background-color: var(--color-modals-background);
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

    // Readonly mode: renders the current selection as plain text (no dropdown, no create button).
    readonly readonly = input<boolean>(false);

    // A config id left out of the dropdown options (e.g. the primary model, when picking a fallback).
    // It is not hidden from the trigger if it is already the selected value.
    readonly excludedConfigId = input<number | null>(null);

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
    protected readonly panelMinWidthPx = PANEL_MIN_WIDTH_PX;
    public readonly overlayWidth = computed(() => Math.max(this.triggerWidth(), PANEL_MIN_WIDTH_PX));
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

    public readonly groupedConfigs = computed(() => {
        const groups = new Map<string, SelectorConfig[]>();
        for (const config of this.filteredConfigs()) {
            const provider = config.providerDetails?.name || 'Other';
            groups.set(provider, [...(groups.get(provider) ?? []), config]);
        }
        return [...groups].map(([provider, configs]) => ({ provider, configs }));
    });

    public readonly selectedConfig = computed<SelectorConfig | null>(() => {
        const id = this.selectedConfigId();
        if (id == null) return null;
        return this.configs().find((c) => c.id === id) ?? null;
    });

    public readonly filteredConfigs = computed<SelectorConfig[]>(() => {
        const term = this.searchTerm().trim().toLowerCase();
        const excludedId = this.excludedConfigId();
        const configs = this.configs().filter((config) => config.id !== excludedId);
        if (!term) return configs;
        return configs.filter((config) => {
            const modelName = config.modelDetails?.name?.toLowerCase() || '';
            const customName = config.custom_name?.toLowerCase() || '';
            const providerName = config.providerDetails?.name?.toLowerCase() || '';
            return modelName.includes(term) || customName.includes(term) || providerName.includes(term);
        });
    });

    // Below first; flip above or align to the trigger's end when the panel would clip on the right.
    readonly overlayPositions: ConnectedPosition[] = [
        { originX: 'start', originY: 'bottom', overlayX: 'start', overlayY: 'top', offsetY: 4 },
        { originX: 'end', originY: 'bottom', overlayX: 'end', overlayY: 'top', offsetY: 4 },
        { originX: 'start', originY: 'top', overlayX: 'start', overlayY: 'bottom', offsetY: -4 },
        { originX: 'end', originY: 'top', overlayX: 'end', overlayY: 'bottom', offsetY: -4 },
    ];

    private readonly dropdownId: string;

    // ControlValueAccessor implementation
    private onChange: (value: number | null) => void = () => {};
    private onTouched: () => void = () => {};

    constructor() {
        // Generate unique ID for this dropdown instance
        this.dropdownId = `llm-selector-${Math.random().toString(36).slice(2, 11)}`;
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
        if (this.readonly()) return;
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

    providerName(provider: string): string {
        return providerDisplayName(provider);
    }

    onCreateLlm(): void {
        if (this.kind() === 'realtime') {
            this.dialog.open(VoiceModelConfigDialogComponent, { autoFocus: false, height: '90vh', width: '600px' });
            return;
        }
        const data: ModelConfigDialogData = { kind: 'llm' };
        this.dialog.open(ModelConfigDialogComponent, { autoFocus: false, data });
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

    protected readonly ResourceCode = ResourceCode;
    protected readonly ActionCode = ActionCode;
}
