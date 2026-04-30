import { CommonModule } from '@angular/common';
import {
    ChangeDetectionStrategy,
    Component,
    computed,
    DestroyRef,
    inject,
    input,
    OnInit,
    signal,
    WritableSignal,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { FormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';
import {
    ButtonComponent,
    ConfirmationDialogData,
    ConfirmationDialogService,
    CustomInputComponent,
    HelpTooltipComponent,
    SelectComponent,
    SelectItem,
} from '@shared/components';
import { MATERIAL_FORMS } from '@shared/material-forms';
import { LLMProvider, ModelTypes } from '@shared/models';
import {
    EmbeddingConfigStorageService,
    LlmConfigStorageService,
    LlmProvidersStorageService,
    RealtimeConfigStorageService,
    TranscriptionConfigStorageService,
} from '@shared/services';
import { getProviderIconPath } from '@shared/utils';
import { EMPTY, filter, finalize, forkJoin, of } from 'rxjs';
import { catchError, map, switchMap, tap } from 'rxjs/operators';

import { ToastService } from '../../../../services/notifications';
import { ConfigureModelsTabId } from '../../enums/configure-models-tab-id.enum';
import { CreateQuickstartRequest } from '../../models/quickstart.model';
import { DefaultModelsStorageService } from '../../services/default-models-storage.service';
import { QuickstartService } from '../../services/quickstart.service';

@Component({
    selector: 'app-quickstart-section',
    imports: [
        CommonModule,
        ReactiveFormsModule,
        MATERIAL_FORMS,
        CustomInputComponent,
        ButtonComponent,
        HelpTooltipComponent,
        SelectComponent,
    ],
    templateUrl: './quickstart-section.component.html',
    styleUrls: ['./quickstart-section.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class QuickstartSectionComponent implements OnInit {
    private readonly fb = inject(FormBuilder);
    private readonly confirmation = inject(ConfirmationDialogService);
    private readonly providersStorageService = inject(LlmProvidersStorageService);
    private readonly llmConfigStorageService = inject(LlmConfigStorageService);
    private readonly embeddingConfigStorageService = inject(EmbeddingConfigStorageService);
    private readonly realtimeConfigStorageService = inject(RealtimeConfigStorageService);
    private readonly transcriptionConfigStorageService = inject(TranscriptionConfigStorageService);
    private readonly quickstartService = inject(QuickstartService);
    private readonly defaultModelsStorageService = inject(DefaultModelsStorageService);
    private readonly destroyRef = inject(DestroyRef);
    private readonly toast = inject(ToastService);

    public activeTabSignal = input.required<WritableSignal<ConfigureModelsTabId>>();

    public readonly quickStartForm = this.fb.group({
        apiKey: ['', [Validators.required]],
        provider: [null, [Validators.required]],
    });

    public readonly quickstartCards = {
        activated: {
            title: 'Quickstart successfully activated',
            showIcon: true,
            text1: `Your Quick Start provider has been applied to recommended default LLMs.`,
            text2: `To ensure optimal performance, please review and assign models for the remaining tasks.`,
            actionText: 'Review default models',
            action: () => this.onReviewDefaults(),
        },
        updated: {
            title: 'Update default models?',
            showIcon: false,
            text1: `Would you like to use it as the default model across all supported tasks?`,
            text2: `This will replace the currently assigned default models.`,
            actionText: 'Update default models',
            action: () => this.onUpdateDefaults(),
        },
        synced: {
            title: 'Default models successfully updated',
            showIcon: true,
            text1: `Your new LLM model has been successfully applied as the default across all supported tasks.`,
            text2: `You can review or adjust these assignments at any time.`,
            actionText: 'Review default models',
            action: () => this.onReviewDefaults(),
        },
    } as const;

    public isSaving = signal(false);
    public providers = signal<LLMProvider[]>([]);
    public quickstartStatus = signal<'activated' | 'updated' | 'synced' | null>(null);

    public providerItems = computed<SelectItem[]>(() => {
        return this.providers().map((provider) => ({
            name: provider.name.replace(/[_-]+/g, ' ').replace(/\b\w/g, (char) => char.toUpperCase()),
            value: provider.name,
            icon: getProviderIconPath(provider.name),
        }));
    });

    get activeCard() {
        const status = this.quickstartStatus();
        return status ? this.quickstartCards[status] : null;
    }

    public ngOnInit(): void {
        this.loadData();
    }

    private loadData(): void {
        forkJoin({
            providers: this.providersStorageService.getProvidersByType(ModelTypes.LLM),
            config: this.quickstartService.getQuickstart(),
        })
            .pipe(
                takeUntilDestroyed(this.destroyRef),
                tap(({ config }) => {
                    if (config.last_config) {
                        this.quickstartStatus.set(config.is_synced ? 'synced' : 'updated');
                    }
                }),
                map(({ providers, config }) => {
                    const providersMap = new Map(providers.map((p) => [p.name, p]));

                    return config.supported_providers
                        .map((name) => providersMap.get(name))
                        .filter((p): p is LLMProvider => !!p);
                }),
                tap((filteredProviders) => this.providers.set(filteredProviders)),
                catchError((error) => {
                    console.error('[Quickstart] Error loading data:', error);
                    this.providers.set([]);
                    return of([]);
                })
            )
            .subscribe();
    }

    public onQuickStart(): void {
        const { apiKey, provider } = this.quickStartForm.value;

        if (!apiKey || !provider) return;

        const data: CreateQuickstartRequest = {
            api_key: apiKey,
            provider,
        };

        this.isSaving.set(true);

        this.quickstartService
            .createQuickstart(data)
            .pipe(
                switchMap(() => {
                    if (this.quickstartStatus() === null) {
                        return this.quickstartService.applyQuickstart();
                    }
                    this.quickstartStatus.set('updated');
                    this.toast.success('Quickstart updated.');
                    this.onReset();
                    return EMPTY;
                }),
                tap(() => {
                    this.onReset();
                    this.quickstartStatus.set('activated');
                    this.toast.success('Quickstart created successfully.');
                }),
                catchError((error) => {
                    console.error(error);
                    this.toast.error('Failed to create/apply quickstart.');
                    return EMPTY;
                }),
                finalize(() => {
                    this.defaultModelsStorageService.markDefaultModelsOutdated();
                    this.llmConfigStorageService.markConfigsOutdated();
                    this.embeddingConfigStorageService.markConfigsOutdated();
                    this.realtimeConfigStorageService.markConfigsOutdated();
                    this.transcriptionConfigStorageService.markConfigsOutdated();
                    this.isSaving.set(false);
                }),
                takeUntilDestroyed(this.destroyRef)
            )
            .subscribe();
    }

    public onReset(): void {
        this.quickStartForm.reset({ apiKey: '' });
    }

    public getProviderIcon(provider: LLMProvider | null): string {
        return getProviderIconPath(provider?.name || null);
    }

    public onReviewDefaults(): void {
        this.activeTabSignal().set(ConfigureModelsTabId.DEFAULT_LLMS);
    }

    public onUpdateDefaults(): void {
        const data: ConfirmationDialogData = {
            title: 'Are you sure?',
            message: 'This will apply Quickstart as a default model for all default LLMs',
            type: 'info',
        };
        this.confirmation
            .confirm(data)
            .pipe(
                takeUntilDestroyed(this.destroyRef),
                filter((result) => result === true),
                switchMap(() => this.quickstartService.applyQuickstart()),
                tap((models) => {
                    this.defaultModelsStorageService.updateModelsInStorage(models);
                    this.quickstartStatus.set('synced');
                    this.toast.success('Models updated successfully.');
                })
            )
            .subscribe();
    }
}
