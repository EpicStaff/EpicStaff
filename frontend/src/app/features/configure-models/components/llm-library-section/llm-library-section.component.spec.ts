import { Dialog } from '@angular/cdk/dialog';
import { DebugElement, signal } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { By } from '@angular/platform-browser';
import { AuthorshipDetailsDialogService, ConfirmationDialogService } from '@shared/components';
import {
    ActionCode,
    ElevenLabsRealtimeConfig,
    EmbeddingConfig,
    GeminiRealtimeConfig,
    GetLlmConfigRequest,
    LlmLibraryModel,
    LlmLibraryProviderGroup,
    ModelTypes,
    OpenAIRealtimeConfig,
    ResourceCode,
    UserSummary,
} from '@shared/models';
import { EmbeddingConfigStorageService, LlmConfigStorageService, LLMLibraryService } from '@shared/services';
import { of } from 'rxjs';

import { PermissionsService } from '../../../../services/auth/permissions.service';
import { ToastService } from '../../../../services/notifications';
import { DefaultModelsStorageService } from '../../services/default-models-storage.service';
import { ElevenLabsRealtimeConfigStorageService } from '../../services/llms/elevenlabs-realtime-config-storage.service';
import { GeminiRealtimeConfigStorageService } from '../../services/llms/gemini-realtime-config-storage.service';
import { OpenAIRealtimeConfigStorageService } from '../../services/llms/openai-realtime-config-storage.service';
import { ConfigCardMoreMenuComponent } from '../config-card-more-menu/config-card-more-menu.component';
import { LlmLibraryCardComponent } from '../llm-library-card/llm-library-card.component';
import { RealtimeConfigDialogComponent } from '../realtime-config-dialog/realtime-config-dialog.component';
import { RealtimeProvider } from '../realtime-config-form/realtime-config-form.component';
import { LlmLibrarySectionComponent } from './llm-library-section.component';

// An LLM config and an embedding config may share an id; the card's config type decides which one is meant.
const SHARED_ID = 3;

const LLM_OWNER: UserSummary = { id: 1, display_name: 'Ivan Bohun', avatar_url: null };
const EMBEDDING_OWNER: UserSummary = { id: 2, display_name: 'Olga Mageria', avatar_url: null };

const LLM_CONFIG: GetLlmConfigRequest = {
    id: SHARED_ID,
    custom_name: 'gpt-4.1-chat',
    model: 10,
    api_key_secret_id: null,
    temperature: 0.7,
    top_p: null,
    stop: null,
    max_tokens: null,
    presence_penalty: null,
    frequency_penalty: null,
    logit_bias: null,
    seed: null,
    timeout: null,
    reasoning_effort: null,
    is_visible: true,
    input_cost_per_token: null,
    output_cost_per_token: null,
    tags: [],
    created_at: '2026-03-12T13:28:23Z',
    created_by: LLM_OWNER,
    last_edited_by: null,
    last_edited_at: null,
};

const EMBEDDING_CONFIG: EmbeddingConfig = {
    id: SHARED_ID,
    custom_name: 'text-embedding-3',
    model: 20,
    task_type: 'retrieval_document',
    api_key_secret_id: null,
    is_visible: true,
    extra_headers: {},
    created_at: '2026-04-01T08:00:00Z',
    created_by: EMBEDDING_OWNER,
    last_edited_by: EMBEDDING_OWNER,
    last_edited_at: '2026-04-02T08:00:00Z',
};

const VOICE_OWNER: UserSummary = { id: 3, display_name: 'Taras Shevchenko', avatar_url: null };

const OPENAI_VOICE_CONFIG: OpenAIRealtimeConfig = {
    id: 11,
    custom_name: 'OpenAI voice',
    api_key_secret_id: null,
    model_name: 'gpt-realtime-1.5',
    base_url: null,
    transcription_model_name: 'whisper-1',
    transcription_api_key_secret_id: null,
    voice_recognition_prompt: null,
    created_at: '2026-05-01T10:00:00Z',
    created_by: VOICE_OWNER,
    last_edited_by: null,
    last_edited_at: null,
};

const ELEVENLABS_VOICE_CONFIG: ElevenLabsRealtimeConfig = {
    id: 12,
    custom_name: 'ElevenLabs voice',
    api_key_secret_id: null,
    model_name: 'eleven_turbo_v2_5',
    language: null,
    created_at: '2026-05-02T10:00:00Z',
    created_by: VOICE_OWNER,
    last_edited_by: VOICE_OWNER,
    last_edited_at: '2026-05-03T10:00:00Z',
};

const GEMINI_VOICE_CONFIG: GeminiRealtimeConfig = {
    id: 13,
    custom_name: 'Gemini voice',
    api_key_secret_id: null,
    model_name: 'gemini-3.1-flash-live-preview',
    voice_recognition_prompt: null,
    created_at: null,
    created_by: null,
    last_edited_by: null,
    last_edited_at: null,
};

type VoiceConfig = OpenAIRealtimeConfig | ElevenLabsRealtimeConfig | GeminiRealtimeConfig;

const VOICE_CONFIGS: Record<RealtimeProvider, VoiceConfig> = {
    openai: OPENAI_VOICE_CONFIG,
    elevenlabs: ELEVENLABS_VOICE_CONFIG,
    gemini: GEMINI_VOICE_CONFIG,
};

function libraryModel(configType: ModelTypes, id: number): LlmLibraryModel {
    return {
        id,
        customName: `${configType}-${id}`,
        modelName: `${configType}-model`,
        tags: [],
        temperature: 0.7,
        usedByCount: null,
        configType,
        isDeprecated: false,
    };
}

function providerGroup(configType: ModelTypes, models: LlmLibraryModel[]): LlmLibraryProviderGroup {
    return { id: `openai-${configType}`, providerName: 'OpenAI', providerIconPath: 'openai', models, configType };
}

/** An in-memory voice config storage: deleting a config removes it from `configs`, as the real one does. */
function realtimeStorageFake(initial: VoiceConfig[] = []): object {
    const configs = signal(initial);
    return {
        configs,
        getAllConfigs: () => of(configs()),
        deleteConfig: (id: number) => {
            configs.update((list) => list.filter((config) => config.id !== id));
            return of(undefined);
        },
    };
}

function render(
    models: LlmLibraryModel[],
    { voiceConfigs = [], grantedActions = [] }: { voiceConfigs?: VoiceConfig[]; grantedActions?: ActionCode[] } = {}
): {
    fixture: ComponentFixture<LlmLibrarySectionComponent>;
    open: ReturnType<typeof vi.fn>;
    openDialog: ReturnType<typeof vi.fn>;
} {
    const open = vi.fn();
    const openDialog = vi.fn();
    const libraryService = {
        providerGroups: signal(
            [ModelTypes.LLM, ModelTypes.EMBEDDING].map((type) =>
                providerGroup(
                    type,
                    models.filter((model) => model.configType === type)
                )
            )
        ),
        loadLlmData: () => of(undefined),
        loadEmbeddingData: () => of(undefined),
        loadRealtimeData: () => of(undefined),
        loadTranscriptionData: () => of(undefined),
    };
    TestBed.configureTestingModule({
        providers: [
            { provide: LLMLibraryService, useValue: libraryService },
            { provide: LlmConfigStorageService, useValue: { configs: signal([LLM_CONFIG]) } },
            { provide: EmbeddingConfigStorageService, useValue: { configs: signal([EMBEDDING_CONFIG]) } },
            {
                provide: OpenAIRealtimeConfigStorageService,
                useValue: realtimeStorageFake(voiceConfigs.filter((config) => config === OPENAI_VOICE_CONFIG)),
            },
            {
                provide: ElevenLabsRealtimeConfigStorageService,
                useValue: realtimeStorageFake(voiceConfigs.filter((config) => config === ELEVENLABS_VOICE_CONFIG)),
            },
            {
                provide: GeminiRealtimeConfigStorageService,
                useValue: realtimeStorageFake(voiceConfigs.filter((config) => config === GEMINI_VOICE_CONFIG)),
            },
            { provide: AuthorshipDetailsDialogService, useValue: { open } },
            { provide: ConfirmationDialogService, useValue: { confirmDelete: () => of(true) } },
            { provide: DefaultModelsStorageService, useValue: {} },
            { provide: ToastService, useValue: { success: vi.fn(), error: vi.fn() } },
            { provide: Dialog, useValue: { open: openDialog } },
            {
                provide: PermissionsService,
                useValue: { can: (_resource: ResourceCode, action: ActionCode) => grantedActions.includes(action) },
            },
        ],
    });
    const fixture = TestBed.createComponent(LlmLibrarySectionComponent);
    fixture.detectChanges();
    return { fixture, open, openDialog };
}

/** Fires the card's "View Details" output, as choosing the menu item does; returns the card's ⋮ trigger. */
function viewDetailsOn(fixture: ComponentFixture<LlmLibrarySectionComponent>, model: LlmLibraryModel): HTMLElement {
    const cardElement = fixture.debugElement
        .queryAll(By.directive(LlmLibraryCardComponent))
        .find((debugElement) => (debugElement.componentInstance as LlmLibraryCardComponent).model() === model)!;
    const trigger = (cardElement.nativeElement as HTMLElement).querySelector<HTMLElement>(
        '[aria-label="More actions"]'
    )!;
    (cardElement.componentInstance as LlmLibraryCardComponent).viewDetailsClick.emit({ model, trigger });
    return trigger;
}

describe('LlmLibrarySectionComponent "View Details"', () => {
    it('opens "Configuration Details" with the LLM config of an LLM card', () => {
        const llmModel = libraryModel(ModelTypes.LLM, SHARED_ID);
        const { fixture, open } = render([llmModel, libraryModel(ModelTypes.EMBEDDING, SHARED_ID)]);

        const trigger = viewDetailsOn(fixture, llmModel);

        expect(open).toHaveBeenCalledExactlyOnceWith('Configuration Details', LLM_CONFIG, trigger);
    });

    it('opens "Configuration Details" with the embedding config of an embedding card sharing the id', () => {
        const embeddingModel = libraryModel(ModelTypes.EMBEDDING, SHARED_ID);
        const { fixture, open } = render([libraryModel(ModelTypes.LLM, SHARED_ID), embeddingModel]);

        const trigger = viewDetailsOn(fixture, embeddingModel);

        expect(open).toHaveBeenCalledExactlyOnceWith('Configuration Details', EMBEDDING_CONFIG, trigger);
    });

    it('opens nothing when the config is no longer in storage', () => {
        const staleModel = libraryModel(ModelTypes.LLM, 99);
        const { fixture, open } = render([staleModel]);

        viewDetailsOn(fixture, staleModel);

        expect(open).not.toHaveBeenCalled();
    });
});

/** The voice card showing `config`, found by its custom name. */
function voiceCard(
    fixture: ComponentFixture<LlmLibrarySectionComponent>,
    config: VoiceConfig
): DebugElement | undefined {
    return fixture.debugElement
        .queryAll(By.directive(LlmLibraryCardComponent))
        .find((card) => (card.componentInstance as LlmLibraryCardComponent).model().customName === config.custom_name);
}

function voiceCardButton(card: DebugElement, label: string): HTMLButtonElement {
    return (card.nativeElement as HTMLElement).querySelector<HTMLButtonElement>(`button[aria-label="${label}"]`)!;
}

describe('LlmLibrarySectionComponent voice config cards', () => {
    it.each(Object.entries(VOICE_CONFIGS))(
        'shows a %s card like an LLM card: custom name on top, model name below, no temperature',
        (_, config) => {
            const { fixture } = render([], { voiceConfigs: [config] });

            const card = voiceCard(fixture, config)!.nativeElement as HTMLElement;

            expect(card.querySelector('.llm-card__model')!.textContent!.trim()).toBe(config.custom_name);
            expect(card.querySelector('.llm-card__name')!.textContent!.trim()).toBe(config.model_name);
            expect(card.textContent).not.toContain('°');
        }
    );

    it.each(Object.entries(VOICE_CONFIGS))('places the ⋮ button before edit and delete on a %s card', (_, config) => {
        const { fixture } = render([], {
            voiceConfigs: [config],
            grantedActions: [ActionCode.Update, ActionCode.Delete],
        });

        const buttons = (voiceCard(fixture, config)!.nativeElement as HTMLElement).querySelectorAll('button');

        expect(Array.from(buttons, (button) => button.getAttribute('aria-label'))).toEqual([
            'More actions',
            `Edit ${config.custom_name}`,
            `Delete ${config.custom_name}`,
        ]);
    });

    it.each(Object.entries(VOICE_CONFIGS))(
        'opens "Configuration Details" with the config of a %s card when "View Details" is chosen',
        (_, config) => {
            const { fixture, open } = render([], { voiceConfigs: Object.values(VOICE_CONFIGS) });
            const card = voiceCard(fixture, config)!;
            const trigger = voiceCardButton(card, 'More actions');

            (
                card.query(By.directive(ConfigCardMoreMenuComponent)).componentInstance as ConfigCardMoreMenuComponent
            ).viewDetailsClick.emit(trigger);

            expect(open).toHaveBeenCalledExactlyOnceWith('Configuration Details', config, trigger);
        }
    );

    it.each(Object.entries(VOICE_CONFIGS) as [RealtimeProvider, VoiceConfig][])(
        'opens the voice config dialog for the %s config when its Edit button is clicked',
        (provider, config) => {
            const { fixture, openDialog } = render([], {
                voiceConfigs: Object.values(VOICE_CONFIGS),
                grantedActions: [ActionCode.Update],
            });

            voiceCardButton(voiceCard(fixture, config)!, `Edit ${config.custom_name}`).click();

            expect(openDialog).toHaveBeenCalledExactlyOnceWith(
                RealtimeConfigDialogComponent,
                expect.objectContaining({ data: { config, provider } })
            );
        }
    );

    it('removes only the deleted voice card once the deletion is confirmed', () => {
        const { fixture } = render([], {
            voiceConfigs: Object.values(VOICE_CONFIGS),
            grantedActions: [ActionCode.Delete],
        });

        voiceCardButton(
            voiceCard(fixture, ELEVENLABS_VOICE_CONFIG)!,
            `Delete ${ELEVENLABS_VOICE_CONFIG.custom_name}`
        ).click();
        fixture.detectChanges();

        expect(voiceCard(fixture, ELEVENLABS_VOICE_CONFIG)).toBeUndefined();
        expect(voiceCard(fixture, OPENAI_VOICE_CONFIG)).toBeDefined();
        expect(voiceCard(fixture, GEMINI_VOICE_CONFIG)).toBeDefined();
    });

    it('offers only the ⋮ button to a user who can only read configurations', () => {
        const { fixture } = render([], { voiceConfigs: [OPENAI_VOICE_CONFIG] });

        const buttons = (voiceCard(fixture, OPENAI_VOICE_CONFIG)!.nativeElement as HTMLElement).querySelectorAll(
            'button'
        );

        expect(buttons).toHaveLength(1);
        expect(buttons[0].getAttribute('aria-label')).toBe('More actions');
    });
});
