import { Dialog } from '@angular/cdk/dialog';
import { OverlayContainer } from '@angular/cdk/overlay';
import { DebugElement, signal } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { By } from '@angular/platform-browser';
import { ActivatedRoute, convertToParamMap, Router } from '@angular/router';
import {
    AuthorshipDetailsDialogService,
    EmbeddingModelConfigDialogComponent,
    LlmModelConfigDialogComponent,
} from '@shared/components';
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
    SystemOneConfig,
    UserSummary,
} from '@shared/models';
import {
    BulkDeleteService,
    EmbeddingConfigStorageService,
    LlmConfigStorageService,
    LLMLibraryService,
    SystemOneConfigStorageService,
} from '@shared/services';
import { EMPTY, of } from 'rxjs';

import { PermissionsService } from '../../../../services/auth/permissions.service';
import { ToastService } from '../../../../services/notifications';
import { DefaultModelsStorageService } from '../../services/default-models-storage.service';
import { ElevenLabsRealtimeConfigStorageService } from '../../services/llms/elevenlabs-realtime-config-storage.service';
import { GeminiRealtimeConfigStorageService } from '../../services/llms/gemini-realtime-config-storage.service';
import { OpenAIRealtimeConfigStorageService } from '../../services/llms/openai-realtime-config-storage.service';
import { AddConfigurationDialogComponent } from '../add-configuration-dialog/add-configuration-dialog.component';
import { ConfigCardMoreMenuComponent } from '../config-card-more-menu/config-card-more-menu.component';
import { LlmLibraryCardComponent } from '../llm-library-card/llm-library-card.component';
import { RealtimeConfigDialogComponent } from '../realtime-config-dialog/realtime-config-dialog.component';
import { RealtimeProvider } from '../realtime-config-form/realtime-config-form.component';
import { SystemOneConfigDialogComponent } from '../system-one-config-dialog/system-one-config-dialog.component';
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

const TYPESAFE_CONFIG: SystemOneConfig = {
    id: 21,
    custom_name: 'Jev prod',
    provider: 'typesafe',
    model_name: 'jev-1.14.0',
    api_key_secret_id: 5,
    llm_config: null,
    created_at: '2026-10-01T10:00:00Z',
    created_by: VOICE_OWNER,
    last_edited_by: null,
    last_edited_at: null,
};

const LLM_BACKED_CONFIG: SystemOneConfig = {
    ...TYPESAFE_CONFIG,
    id: 22,
    custom_name: 'Judge',
    provider: 'llm',
    model_name: null,
    api_key_secret_id: null,
    llm_config: SHARED_ID,
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

// The header buttons collapse on overflow and observe their size; jsdom has no ResizeObserver.
class ResizeObserverStub {
    observe(): void {}
    unobserve(): void {}
    disconnect(): void {}
}

beforeEach(() => vi.stubGlobal('ResizeObserver', ResizeObserverStub));
afterEach(() => vi.unstubAllGlobals());

function realtimeStorageStub(configs: VoiceConfig[] = []): object {
    return { configs: signal(configs), getAllConfigs: () => of(configs) };
}

function render(
    models: LlmLibraryModel[],
    {
        voiceConfigs = [],
        systemOneConfigs = [],
        grantedActions = [],
        queryParams = {},
    }: {
        voiceConfigs?: VoiceConfig[];
        systemOneConfigs?: SystemOneConfig[];
        grantedActions?: ActionCode[];
        queryParams?: Record<string, string>;
    } = {}
): {
    fixture: ComponentFixture<LlmLibrarySectionComponent>;
    open: ReturnType<typeof vi.fn>;
    openDialog: ReturnType<typeof vi.fn>;
    runBulkDelete: ReturnType<typeof vi.fn>;
} {
    const open = vi.fn();
    const openDialog = vi.fn();
    const runBulkDelete = vi.fn(() => EMPTY);
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
                useValue: realtimeStorageStub(voiceConfigs.filter((config) => config === OPENAI_VOICE_CONFIG)),
            },
            {
                provide: ElevenLabsRealtimeConfigStorageService,
                useValue: realtimeStorageStub(voiceConfigs.filter((config) => config === ELEVENLABS_VOICE_CONFIG)),
            },
            {
                provide: GeminiRealtimeConfigStorageService,
                useValue: realtimeStorageStub(voiceConfigs.filter((config) => config === GEMINI_VOICE_CONFIG)),
            },
            {
                provide: SystemOneConfigStorageService,
                useValue: { configs: signal(systemOneConfigs), getAllConfigs: vi.fn(() => of(systemOneConfigs)) },
            },
            { provide: AuthorshipDetailsDialogService, useValue: { open } },
            { provide: BulkDeleteService, useValue: { run: runBulkDelete } },
            { provide: DefaultModelsStorageService, useValue: { markDefaultModelsOutdated: vi.fn() } },
            { provide: ToastService, useValue: { success: vi.fn(), error: vi.fn() } },
            { provide: Dialog, useValue: { open: openDialog } },
            {
                provide: PermissionsService,
                useValue: { can: (_resource: ResourceCode, action: ActionCode) => grantedActions.includes(action) },
            },
            { provide: ActivatedRoute, useValue: { snapshot: { queryParamMap: convertToParamMap(queryParams) } } },
            {
                provide: Router,
                useValue: { navigate: () => Promise.resolve(true), lastSuccessfulNavigation: () => null },
            },
        ],
    });
    const fixture = TestBed.createComponent(LlmLibrarySectionComponent);
    fixture.detectChanges();
    return { fixture, open, openDialog, runBulkDelete };
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

describe('LlmLibrarySectionComponent select mode', () => {
    function headerButtonLabels(fixture: ComponentFixture<LlmLibrarySectionComponent>): string[] {
        return Array.from(
            (fixture.nativeElement as HTMLElement).querySelectorAll('.header-right > app-button'),
            (button) => button.textContent?.trim() ?? ''
        );
    }

    function enterSelectMode(fixture: ComponentFixture<LlmLibrarySectionComponent>): void {
        (fixture.nativeElement as HTMLElement)
            .querySelector<HTMLButtonElement>('app-bulk-select-dropdown .bulk-select__main')!
            .click();
        fixture.detectChanges();
    }

    function tickCard(
        fixture: ComponentFixture<LlmLibrarySectionComponent>,
        model: LlmLibraryModel,
        selected: boolean
    ): void {
        const card = fixture.debugElement
            .queryAll(By.directive(LlmLibraryCardComponent))
            .find((debugElement) => (debugElement.componentInstance as LlmLibraryCardComponent).model() === model)!;
        (card.componentInstance as LlmLibraryCardComponent).selectedChange.emit(selected);
        fixture.detectChanges();
    }

    function selectLabel(fixture: ComponentFixture<LlmLibrarySectionComponent>): string {
        const main = (fixture.nativeElement as HTMLElement).querySelector(
            'app-bulk-select-dropdown .bulk-select__main'
        )!;
        return main.textContent?.replace(/\s+/g, ' ').trim() ?? '';
    }

    it('keeps "Add Configuration" in select mode until a card is ticked, then shows "Select (1)" and a red "Delete"', () => {
        const model = libraryModel(ModelTypes.LLM, SHARED_ID);
        const { fixture } = render([model], { grantedActions: [ActionCode.Create, ActionCode.Delete] });

        enterSelectMode(fixture);

        expect(fixture.componentInstance.selectMode()).toBe(true);
        expect(headerButtonLabels(fixture)).toEqual(['Add Configuration']);
        expect(selectLabel(fixture)).toBe('Select');

        tickCard(fixture, model, true);

        expect(selectLabel(fixture)).toBe('Select (1)');
        expect(headerButtonLabels(fixture)).toEqual(['Delete']);
        const deleteButton = (fixture.nativeElement as HTMLElement).querySelector<HTMLButtonElement>(
            '.header-right > app-button button'
        )!;
        expect(deleteButton.classList).toContain('btn-danger');
        expect(deleteButton.querySelector('app-svg-icon.btn-icon.left use')?.getAttribute('href')).toBe('#icon-trash');
        expect(deleteButton.disabled).toBe(false);
    });

    it('leaves select mode on a second click of "Select" with nothing ticked', () => {
        const { fixture } = render([libraryModel(ModelTypes.LLM, SHARED_ID)], {
            grantedActions: [ActionCode.Delete],
        });
        enterSelectMode(fixture);
        expect(fixture.componentInstance.selectMode()).toBe(true);

        enterSelectMode(fixture);

        expect(fixture.componentInstance.selectMode()).toBe(false);
        expect((fixture.nativeElement as HTMLElement).querySelector('.llm-card__checkbox')).toBeNull();
    });

    it('goes back to a plain "Select" in select mode after "Clear Selection"', () => {
        const model = libraryModel(ModelTypes.LLM, SHARED_ID);
        const { fixture } = render([model], { grantedActions: [ActionCode.Create, ActionCode.Delete] });
        enterSelectMode(fixture);
        tickCard(fixture, model, true);

        chooseMenuItem(fixture, 'Clear Selection');

        expect(fixture.componentInstance.selectedKeys().size).toBe(0);
        expect(fixture.componentInstance.selectMode()).toBe(true);
        expect(selectLabel(fixture)).toBe('Select');
        expect(headerButtonLabels(fixture)).toEqual(['Add Configuration']);
    });

    describe('with nothing ticked', () => {
        function pressEscape(fixture: ComponentFixture<LlmLibrarySectionComponent>): void {
            document.body.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
            fixture.detectChanges();
        }

        function clickOn(fixture: ComponentFixture<LlmLibrarySectionComponent>, element: Element): void {
            (element as HTMLElement).click();
            fixture.detectChanges();
        }

        function cardElement(fixture: ComponentFixture<LlmLibrarySectionComponent>): Element {
            return (fixture.nativeElement as HTMLElement).querySelector('app-llm-library-card')!;
        }

        it('stays in select mode right after the click that enters it', () => {
            const { fixture } = render([libraryModel(ModelTypes.LLM, SHARED_ID)], {
                grantedActions: [ActionCode.Delete],
            });

            enterSelectMode(fixture);

            expect(fixture.componentInstance.selectMode()).toBe(true);
        });

        it('leaves select mode on a click outside the cards and the Select control', () => {
            const { fixture } = render([libraryModel(ModelTypes.LLM, SHARED_ID)], {
                grantedActions: [ActionCode.Delete],
            });
            enterSelectMode(fixture);

            clickOn(fixture, (fixture.nativeElement as HTMLElement).querySelector('.title')!);

            expect(fixture.componentInstance.selectMode()).toBe(false);
            expect((fixture.nativeElement as HTMLElement).querySelector('.llm-card__checkbox')).toBeNull();
        });

        it.each([
            ['a card', (fixture: ComponentFixture<LlmLibrarySectionComponent>) => cardElement(fixture)],
            [
                'an overlay',
                () => {
                    const pane = document.createElement('div');
                    TestBed.inject(OverlayContainer).getContainerElement().appendChild(pane);
                    return pane;
                },
            ],
        ])('stays in select mode on a click in %s', (_place, elementOf) => {
            const { fixture } = render([libraryModel(ModelTypes.LLM, SHARED_ID)], {
                grantedActions: [ActionCode.Delete],
            });
            enterSelectMode(fixture);

            clickOn(fixture, elementOf(fixture));

            expect(fixture.componentInstance.selectMode()).toBe(true);
        });

        it('leaves select mode on Escape and puts the focus on Select', () => {
            const { fixture } = render([libraryModel(ModelTypes.LLM, SHARED_ID)], {
                grantedActions: [ActionCode.Delete],
            });
            enterSelectMode(fixture);

            pressEscape(fixture);

            expect(fixture.componentInstance.selectMode()).toBe(false);
            expect(document.activeElement).toBe(
                (fixture.nativeElement as HTMLElement).querySelector('app-bulk-select-dropdown .bulk-select__main')
            );
        });

        it('leaves select mode on Escape in the search and keeps the focus there', () => {
            const { fixture } = render([libraryModel(ModelTypes.LLM, SHARED_ID)], {
                grantedActions: [ActionCode.Delete],
            });
            enterSelectMode(fixture);
            const search = (fixture.nativeElement as HTMLElement).querySelector<HTMLInputElement>('app-search input')!;
            search.focus();

            search.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
            fixture.detectChanges();

            expect(fixture.componentInstance.selectMode()).toBe(false);
            expect(document.activeElement).toBe(search);
        });

        it('leaves Escape to what is above the page when that takes it', () => {
            const { fixture } = render([libraryModel(ModelTypes.LLM, SHARED_ID)], {
                grantedActions: [ActionCode.Delete],
            });
            enterSelectMode(fixture);
            const escape = new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true });
            escape.preventDefault();

            document.body.dispatchEvent(escape);
            fixture.detectChanges();

            expect(fixture.componentInstance.selectMode()).toBe(true);
        });

        it('changes nothing on an outside click or Escape once a card is ticked', () => {
            const model = libraryModel(ModelTypes.LLM, SHARED_ID);
            const { fixture } = render([model], { grantedActions: [ActionCode.Delete] });
            enterSelectMode(fixture);
            tickCard(fixture, model, true);

            clickOn(fixture, (fixture.nativeElement as HTMLElement).querySelector('.title')!);
            pressEscape(fixture);

            expect(fixture.componentInstance.selectMode()).toBe(true);
            expect(fixture.componentInstance.selectedKeys().size).toBe(1);
        });
    });

    it('ends select mode when the last ticked card is unticked', () => {
        const model = libraryModel(ModelTypes.LLM, SHARED_ID);
        const { fixture } = render([model], { grantedActions: [ActionCode.Create, ActionCode.Delete] });
        enterSelectMode(fixture);
        tickCard(fixture, model, true);

        tickCard(fixture, model, false);

        expect(fixture.componentInstance.selectMode()).toBe(false);
        expect(headerButtonLabels(fixture)).toEqual(['Add Configuration']);
        expect((fixture.nativeElement as HTMLElement).querySelector('.llm-card__checkbox')).toBeNull();
    });

    it('gives LLM, embedding and voice cards a secondary (light box, dark tick) selection checkbox', () => {
        const { fixture } = render(
            [libraryModel(ModelTypes.LLM, SHARED_ID), libraryModel(ModelTypes.EMBEDDING, SHARED_ID)],
            { voiceConfigs: [OPENAI_VOICE_CONFIG], grantedActions: [ActionCode.Delete] }
        );
        enterSelectMode(fixture);

        const checkboxes = Array.from(
            (fixture.nativeElement as HTMLElement).querySelectorAll('.llm-card__checkbox app-checkbox input')
        );
        expect(checkboxes).toHaveLength(3);
        checkboxes.forEach((checkbox) => expect(checkbox.classList).toContain('secondary'));
    });

    /** Chooses `item` in the menu of "Select (N)", which needs a ticked card. */
    function chooseMenuItem(fixture: ComponentFixture<LlmLibrarySectionComponent>, item: string): void {
        (fixture.nativeElement as HTMLElement)
            .querySelector<HTMLButtonElement>('app-bulk-select-dropdown .bulk-select__main')!
            .click();
        fixture.detectChanges();
        Array.from(document.querySelectorAll<HTMLButtonElement>('.bulk-select-menu__item'))
            .find((button) => button.textContent?.trim() === item)!
            .click();
        fixture.detectChanges();
    }

    it('selects both an LLM and an embedding card sharing an id with "Select All"', () => {
        const llmModel = libraryModel(ModelTypes.LLM, SHARED_ID);
        const { fixture } = render([llmModel, libraryModel(ModelTypes.EMBEDDING, SHARED_ID)], {
            grantedActions: [ActionCode.Delete],
        });
        enterSelectMode(fixture);
        tickCard(fixture, llmModel, true);

        chooseMenuItem(fixture, 'Select All');

        expect(fixture.componentInstance.selectedKeys()).toEqual(
            new Set([`llm:${SHARED_ID}`, `embedding:${SHARED_ID}`])
        );
        expect(fixture.componentInstance.allVisibleSelected()).toBe(true);
    });

    it('opens the Add Configuration dialog from the header', () => {
        const { fixture, openDialog } = render([libraryModel(ModelTypes.LLM, SHARED_ID)], {
            grantedActions: [ActionCode.Create],
        });

        (fixture.nativeElement as HTMLElement)
            .querySelector<HTMLButtonElement>('app-llm-library-header .header-right > app-button button')!
            .click();

        expect(openDialog).toHaveBeenCalledOnce();
        expect(openDialog.mock.calls[0][0]).toBe(AddConfigurationDialogComponent);
    });

    it('puts the focus on Add Configuration once a bulk delete is done', () => {
        const model = libraryModel(ModelTypes.LLM, SHARED_ID);
        const { fixture, runBulkDelete } = render([model], { grantedActions: [ActionCode.Create, ActionCode.Delete] });
        runBulkDelete.mockReturnValue(of([]));
        enterSelectMode(fixture);
        tickCard(fixture, model, true);

        (fixture.nativeElement as HTMLElement)
            .querySelector<HTMLButtonElement>('.header-right > app-button button')!
            .click();
        // A full tick: the focus moves in an after-render hook.
        TestBed.tick();

        expect(headerButtonLabels(fixture)).toEqual(['Add Configuration']);
        expect(document.activeElement).toBe(
            (fixture.nativeElement as HTMLElement).querySelector('.header-right > app-button button')
        );
    });

    it('offers no select dropdown without the delete permission', () => {
        const { fixture } = render([libraryModel(ModelTypes.LLM, SHARED_ID)], { grantedActions: [ActionCode.Create] });

        expect((fixture.nativeElement as HTMLElement).querySelector('app-bulk-select-dropdown')).toBeNull();
    });

    it('orders the header as search, capabilities, Select, then Add Configuration or Delete', () => {
        const model = libraryModel(ModelTypes.LLM, SHARED_ID);
        const { fixture } = render([model], {
            grantedActions: [ActionCode.Create, ActionCode.Delete],
        });
        /** Header items in DOM order: buttons by their label, the filter by its class, the rest by tag. */
        const headerOrder = (): string[] =>
            Array.from((fixture.nativeElement as HTMLElement).querySelector('.header-right')!.children, (child) => {
                if (child.classList.contains('filter')) return 'filter';
                if (child.tagName === 'APP-BUTTON') return child.textContent?.trim() ?? '';
                return child.tagName.toLowerCase();
            });

        expect(headerOrder()).toEqual(['app-search', 'filter', 'app-bulk-select-dropdown', 'Add Configuration']);

        enterSelectMode(fixture);
        tickCard(fixture, model, true);

        expect(headerOrder()).toEqual(['app-search', 'filter', 'app-bulk-select-dropdown', 'Delete']);
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

    it('sends only the clicked voice config to the bulk delete flow', () => {
        const { fixture, runBulkDelete } = render([], {
            voiceConfigs: Object.values(VOICE_CONFIGS),
            grantedActions: [ActionCode.Delete],
        });

        voiceCardButton(
            voiceCard(fixture, ELEVENLABS_VOICE_CONFIG)!,
            `Delete ${ELEVENLABS_VOICE_CONFIG.custom_name}`
        ).click();

        expect(runBulkDelete).toHaveBeenCalledExactlyOnceWith([
            expect.objectContaining({
                target: TestBed.inject(ElevenLabsRealtimeConfigStorageService),
                items: [{ id: ELEVENLABS_VOICE_CONFIG.id, name: ELEVENLABS_VOICE_CONFIG.custom_name }],
            }),
        ]);
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

describe('LlmLibrarySectionComponent System One configs', () => {
    function groupTitles(fixture: ComponentFixture<LlmLibrarySectionComponent>): string[] {
        return Array.from((fixture.nativeElement as HTMLElement).querySelectorAll('.section-title'), (title) =>
            title.textContent!.trim()
        );
    }

    function cardNames(fixture: ComponentFixture<LlmLibrarySectionComponent>): string[] {
        return fixture.debugElement
            .queryAll(By.directive(LlmLibraryCardComponent))
            .map((card) => (card.nativeElement as HTMLElement).querySelector('.llm-card__model')!.textContent!.trim());
    }

    it('lists them under "System One", showing the Jev version or the LLM config used', () => {
        const { fixture } = render([], { systemOneConfigs: [TYPESAFE_CONFIG, LLM_BACKED_CONFIG] });

        expect(groupTitles(fixture)).toEqual(['System One']);
        const cards = fixture.debugElement.queryAll(By.directive(LlmLibraryCardComponent));
        expect(
            cards.map((card) =>
                (card.nativeElement as HTMLElement).querySelector('.llm-card__name')!.textContent!.trim()
            )
        ).toEqual(['jev-1.14.0', 'LLM: gpt-4.1-chat']);
    });

    it('leaves the group out when there are none', () => {
        const { fixture } = render([libraryModel(ModelTypes.LLM, SHARED_ID)]);

        expect(groupTitles(fixture)).not.toContain('System One');
    });

    it('narrows them by name with the shared search', () => {
        const { fixture } = render([], { systemOneConfigs: [TYPESAFE_CONFIG, LLM_BACKED_CONFIG] });

        const input = (fixture.nativeElement as HTMLElement).querySelector<HTMLInputElement>('app-search input')!;
        input.value = 'judge';
        input.dispatchEvent(new Event('input'));
        fixture.detectChanges();

        expect(cardNames(fixture)).toEqual(['Judge']);
    });

    it('opens the System One dialog with the config when its Edit button is clicked', () => {
        const { fixture, openDialog } = render([], {
            systemOneConfigs: [TYPESAFE_CONFIG],
            grantedActions: [ActionCode.Update],
        });

        (fixture.nativeElement as HTMLElement)
            .querySelector<HTMLButtonElement>(`button[aria-label="Edit ${TYPESAFE_CONFIG.custom_name}"]`)!
            .click();

        expect(openDialog).toHaveBeenCalledExactlyOnceWith(
            SystemOneConfigDialogComponent,
            expect.objectContaining({ data: { config: TYPESAFE_CONFIG } })
        );
    });

    it('selects them with "Select All" and deletes them in their own group beside the LLM group', () => {
        const { fixture, runBulkDelete } = render([libraryModel(ModelTypes.LLM, SHARED_ID)], {
            systemOneConfigs: [TYPESAFE_CONFIG],
            grantedActions: [ActionCode.Delete],
        });
        const selectButton = (): HTMLButtonElement =>
            (fixture.nativeElement as HTMLElement).querySelector<HTMLButtonElement>(
                'app-bulk-select-dropdown .bulk-select__main'
            )!;
        selectButton().click();
        fixture.detectChanges();
        // The menu comes with a selection: tick one card first.
        (
            fixture.debugElement.query(By.directive(LlmLibraryCardComponent))
                .componentInstance as LlmLibraryCardComponent
        ).selectedChange.emit(true);
        fixture.detectChanges();
        selectButton().click();
        fixture.detectChanges();
        document.querySelector<HTMLButtonElement>('.bulk-select-menu__item')!.click();
        fixture.detectChanges();

        expect(fixture.componentInstance.selectedKeys()).toEqual(new Set([`llm:${SHARED_ID}`, 'system_one:21']));

        (fixture.nativeElement as HTMLElement)
            .querySelector<HTMLButtonElement>('.header-right > app-button button')!
            .click();

        const groups = runBulkDelete.mock.calls[0][0] as { label: { singular: string }; items: unknown[] }[];
        expect(groups.map((group) => group.label.singular)).toEqual(['LLM config', 'System One config']);
        expect(groups[1].items).toEqual([{ id: 21, name: 'Jev prod' }]);
        expect(groups[1]).toEqual(expect.objectContaining({ target: TestBed.inject(SystemOneConfigStorageService) }));
    });

    it('sends only the clicked System One config to the bulk delete flow', () => {
        const { fixture, runBulkDelete } = render([], {
            systemOneConfigs: [TYPESAFE_CONFIG, LLM_BACKED_CONFIG],
            grantedActions: [ActionCode.Delete],
        });

        (fixture.nativeElement as HTMLElement)
            .querySelector<HTMLButtonElement>(`button[aria-label="Delete ${LLM_BACKED_CONFIG.custom_name}"]`)!
            .click();

        expect(runBulkDelete).toHaveBeenCalledExactlyOnceWith([
            expect.objectContaining({
                target: TestBed.inject(SystemOneConfigStorageService),
                label: { singular: 'System One config', plural: 'System One configs' },
                items: [{ id: 22, name: 'Judge' }],
            }),
        ]);
    });

    it('shows "LLM: not set" for an LLM config whose LLM config is gone', () => {
        const { fixture } = render([], { systemOneConfigs: [{ ...LLM_BACKED_CONFIG, llm_config: null }] });

        expect(cardNames(fixture)).toEqual(['Judge']);
        expect((fixture.nativeElement as HTMLElement).querySelector('.llm-card__name')!.textContent!.trim()).toBe(
            'LLM: not set'
        );
    });

    it('reloads them after an LLM config is deleted, since the server clears their link', () => {
        const { fixture, runBulkDelete } = render([libraryModel(ModelTypes.LLM, SHARED_ID)], {
            systemOneConfigs: [LLM_BACKED_CONFIG],
            grantedActions: [ActionCode.Delete],
        });
        const systemOneStorage = TestBed.inject(SystemOneConfigStorageService);
        const llmStorage = TestBed.inject(LlmConfigStorageService);
        runBulkDelete.mockReturnValueOnce(of([{ group: { target: llmStorage }, response: { deleted_count: 1 } }]));
        vi.mocked(systemOneStorage.getAllConfigs).mockClear();

        (fixture.nativeElement as HTMLElement)
            .querySelector<HTMLButtonElement>(`button[aria-label="Delete llm-${SHARED_ID}"]`)!
            .click();

        expect(systemOneStorage.getAllConfigs).toHaveBeenCalledExactlyOnceWith(true);
    });
});

describe('LlmLibrarySectionComponent ?configType=&configId= deep link', () => {
    const LLM_MODEL = libraryModel(ModelTypes.LLM, SHARED_ID);
    const EMBEDDING_MODEL = libraryModel(ModelTypes.EMBEDDING, SHARED_ID);

    function renderLinked(queryParams: Record<string, string>, grantedActions: ActionCode[] = [ActionCode.Update]) {
        return render([LLM_MODEL, EMBEDDING_MODEL], {
            voiceConfigs: Object.values(VOICE_CONFIGS),
            systemOneConfigs: [TYPESAFE_CONFIG],
            grantedActions,
            queryParams,
        });
    }

    it.each([
        ['llm', SHARED_ID, LlmModelConfigDialogComponent, { configId: SHARED_ID }],
        ['embedding', SHARED_ID, EmbeddingModelConfigDialogComponent, { configId: SHARED_ID }],
        ['system-one', TYPESAFE_CONFIG.id, SystemOneConfigDialogComponent, { config: TYPESAFE_CONFIG }],
        [
            'openai-voice',
            OPENAI_VOICE_CONFIG.id,
            RealtimeConfigDialogComponent,
            { config: OPENAI_VOICE_CONFIG, provider: 'openai' },
        ],
        [
            'elevenlabs-voice',
            ELEVENLABS_VOICE_CONFIG.id,
            RealtimeConfigDialogComponent,
            { config: ELEVENLABS_VOICE_CONFIG, provider: 'elevenlabs' },
        ],
        [
            'gemini-voice',
            GEMINI_VOICE_CONFIG.id,
            RealtimeConfigDialogComponent,
            { config: GEMINI_VOICE_CONFIG, provider: 'gemini' },
        ],
    ])('opens the %s config with id %s in the dialog its Edit button opens', (configType, id, dialog, data) => {
        const { openDialog } = renderLinked({ configType, configId: String(id) });

        expect(openDialog).toHaveBeenCalledExactlyOnceWith(dialog, expect.objectContaining({ data }));
    });

    it('searches the library for the config instead, for a viewer who cannot edit configurations', () => {
        const { fixture, openDialog } = renderLinked(
            { configType: 'system-one', configId: String(TYPESAFE_CONFIG.id) },
            []
        );

        expect(openDialog).not.toHaveBeenCalled();
        expect(fixture.componentInstance.searchQuery()).toBe(TYPESAFE_CONFIG.custom_name);
    });

    it.each([
        ['an unknown id', { configType: 'llm', configId: '999' }],
        ['an id of another config type', { configType: 'system-one', configId: String(SHARED_ID) }],
        ['an unknown config type', { configType: 'transcription', configId: String(SHARED_ID) }],
        ['a config type named after an Object member', { configType: 'constructor', configId: String(SHARED_ID) }],
    ])('opens nothing for %s', (_case, queryParams) => {
        const { fixture, openDialog } = renderLinked(queryParams);

        expect(openDialog).not.toHaveBeenCalled();
        expect(fixture.componentInstance.searchQuery()).toBe('');
    });
});

describe('LlmLibrarySectionComponent sections', () => {
    function sectionElement(fixture: ComponentFixture<LlmLibrarySectionComponent>, title: string): HTMLElement {
        return Array.from(
            (fixture.nativeElement as HTMLElement).querySelectorAll<HTMLElement>('.library-section')
        ).find((section) => section.querySelector('.section-title')!.textContent!.trim() === title)!;
    }

    /** Title, then the count and the providers, or in select mode "ticked / total". */
    function headingText(section: HTMLElement): string {
        return Array.from(
            section.querySelectorAll('.section-title, .section-count, .section-providers, .section-selection'),
            (part) => part.textContent!.replace(/\s+/g, ' ').trim()
        ).join(' ');
    }

    function toggle(fixture: ComponentFixture<LlmLibrarySectionComponent>, title: string): HTMLButtonElement {
        return sectionElement(fixture, title).querySelector<HTMLButtonElement>('.section-toggle')!;
    }

    function sectionBox(fixture: ComponentFixture<LlmLibrarySectionComponent>, title: string): HTMLInputElement {
        return sectionElement(fixture, title).querySelector<HTMLInputElement>('.section-checkbox input')!;
    }

    function tick(
        fixture: ComponentFixture<LlmLibrarySectionComponent>,
        model: LlmLibraryModel,
        selected: boolean
    ): void {
        const card = fixture.debugElement
            .queryAll(By.directive(LlmLibraryCardComponent))
            .find((debugElement) => (debugElement.componentInstance as LlmLibraryCardComponent).model() === model)!;
        (card.componentInstance as LlmLibraryCardComponent).selectedChange.emit(selected);
        fixture.detectChanges();
    }

    function enterSelectMode(fixture: ComponentFixture<LlmLibrarySectionComponent>): void {
        (fixture.nativeElement as HTMLElement)
            .querySelector<HTMLButtonElement>('app-bulk-select-dropdown .bulk-select__main')!
            .click();
        fixture.detectChanges();
    }

    it('heads LLM, Embeddings, Realtime and System One, in that order, each with its card count', () => {
        const { fixture } = render(
            [
                libraryModel(ModelTypes.LLM, SHARED_ID),
                libraryModel(ModelTypes.LLM, 4),
                libraryModel(ModelTypes.EMBEDDING, SHARED_ID),
            ],
            { voiceConfigs: [OPENAI_VOICE_CONFIG, GEMINI_VOICE_CONFIG], systemOneConfigs: [TYPESAFE_CONFIG] }
        );

        expect(
            Array.from(
                (fixture.nativeElement as HTMLElement).querySelectorAll<HTMLElement>('.library-section'),
                headingText
            )
        ).toEqual(['LLM 2', 'Embeddings 1', 'Realtime 2', 'System One 1']);
    });

    it('groups every realtime provider under the one Realtime section', () => {
        const { fixture } = render([], { voiceConfigs: Object.values(VOICE_CONFIGS) });

        const voice = sectionElement(fixture, 'Realtime');

        expect(Array.from(voice.querySelectorAll('.provider-name'), (name) => name.textContent!.trim())).toEqual([
            'OpenAI',
            'ElevenLabs',
            'Gemini',
        ]);
        expect((fixture.nativeElement as HTMLElement).querySelectorAll('.library-section')).toHaveLength(1);
    });

    it('starts open and lists the providers in the heading only while collapsed', () => {
        const { fixture } = render([], { voiceConfigs: Object.values(VOICE_CONFIGS) });
        expect(toggle(fixture, 'Realtime').getAttribute('aria-expanded')).toBe('true');
        expect(headingText(sectionElement(fixture, 'Realtime'))).toBe('Realtime 3');

        toggle(fixture, 'Realtime').click();
        fixture.detectChanges();

        expect(toggle(fixture, 'Realtime').getAttribute('aria-expanded')).toBe('false');
        expect(headingText(sectionElement(fixture, 'Realtime'))).toBe('Realtime 3 OpenAI, ElevenLabs, Gemini');

        toggle(fixture, 'Realtime').click();
        fixture.detectChanges();

        expect(headingText(sectionElement(fixture, 'Realtime'))).toBe('Realtime 3');
    });

    it('stays in select mode when a section box is ticked right after entering it', () => {
        const { fixture } = render([libraryModel(ModelTypes.LLM, SHARED_ID), libraryModel(ModelTypes.LLM, 4)], {
            grantedActions: [ActionCode.Delete],
        });
        enterSelectMode(fixture);

        sectionBox(fixture, 'LLM').click();
        fixture.detectChanges();

        expect(fixture.componentInstance.selectMode()).toBe(true);
        expect(fixture.componentInstance.selectedKeys()).toEqual(new Set([`llm:${SHARED_ID}`, 'llm:4']));
        expect(headingText(sectionElement(fixture, 'LLM'))).toBe('LLM 2 / 2');
    });

    it("ticks a section's cards from its box, and unticks them all from a box with some ticked", () => {
        const llmFirst = libraryModel(ModelTypes.LLM, SHARED_ID);
        const llmSecond = libraryModel(ModelTypes.LLM, 4);
        const embedding = libraryModel(ModelTypes.EMBEDDING, SHARED_ID);
        const { fixture } = render([llmFirst, llmSecond, embedding], { grantedActions: [ActionCode.Delete] });
        enterSelectMode(fixture);
        tick(fixture, embedding, true);

        sectionBox(fixture, 'LLM').click();
        fixture.detectChanges();
        tick(fixture, llmSecond, false);

        expect(headingText(sectionElement(fixture, 'LLM'))).toBe('LLM 1 / 2');
        expect(sectionBox(fixture, 'LLM').indeterminate).toBe(true);

        sectionBox(fixture, 'LLM').click();
        fixture.detectChanges();

        expect(fixture.componentInstance.selectedKeys()).toEqual(new Set([`embedding:${SHARED_ID}`]));
        expect(headingText(sectionElement(fixture, 'LLM'))).toBe('LLM 0 / 2');
        expect(sectionBox(fixture, 'LLM').checked).toBe(false);
        expect(headingText(sectionElement(fixture, 'Embeddings'))).toBe('Embeddings 1 / 1');
    });
});

describe('LlmLibrarySectionComponent Capabilities filter and search', () => {
    function sectionTitles(fixture: ComponentFixture<LlmLibrarySectionComponent>): string[] {
        return Array.from((fixture.nativeElement as HTMLElement).querySelectorAll('.section-title'), (title) =>
            title.textContent!.trim()
        );
    }

    function emptyHint(fixture: ComponentFixture<LlmLibrarySectionComponent>): string | undefined {
        return (fixture.nativeElement as HTMLElement).querySelector('.empty-hint')?.textContent?.trim();
    }

    function chooseCapability(fixture: ComponentFixture<LlmLibrarySectionComponent>, name: string): void {
        (fixture.nativeElement as HTMLElement).querySelector<HTMLButtonElement>('.filter .selector__btn')!.click();
        fixture.detectChanges();
        Array.from(document.querySelectorAll<HTMLButtonElement>('.selector__option'))
            .find((option) => option.querySelector('.selector__text')?.textContent?.trim() === name)!
            .click();
        fixture.detectChanges();
    }

    function search(fixture: ComponentFixture<LlmLibrarySectionComponent>, query: string): void {
        const input = (fixture.nativeElement as HTMLElement).querySelector<HTMLInputElement>('app-search input')!;
        input.value = query;
        input.dispatchEvent(new Event('input'));
        fixture.detectChanges();
    }

    function selectButton(fixture: ComponentFixture<LlmLibrarySectionComponent>): HTMLButtonElement | null {
        return (fixture.nativeElement as HTMLElement).querySelector<HTMLButtonElement>(
            'app-bulk-select-dropdown .bulk-select__main'
        );
    }

    function selectLabel(fixture: ComponentFixture<LlmLibrarySectionComponent>): string {
        return selectButton(fixture)!.textContent!.replace(/\s+/g, ' ').trim();
    }

    function enterSelectMode(fixture: ComponentFixture<LlmLibrarySectionComponent>): void {
        selectButton(fixture)!.click();
        fixture.detectChanges();
    }

    function tick(fixture: ComponentFixture<LlmLibrarySectionComponent>, model: LlmLibraryModel): void {
        const card = fixture.debugElement
            .queryAll(By.directive(LlmLibraryCardComponent))
            .find((debugElement) => (debugElement.componentInstance as LlmLibraryCardComponent).model() === model)!;
        (card.componentInstance as LlmLibraryCardComponent).selectedChange.emit(true);
        fixture.detectChanges();
    }

    it('shows only the chosen section, and all of them again with "All capabilities"', () => {
        const { fixture } = render(
            [libraryModel(ModelTypes.LLM, SHARED_ID), libraryModel(ModelTypes.EMBEDDING, SHARED_ID)],
            { voiceConfigs: [OPENAI_VOICE_CONFIG], systemOneConfigs: [TYPESAFE_CONFIG] }
        );

        chooseCapability(fixture, 'Realtime');

        expect(sectionTitles(fixture)).toEqual(['Realtime']);

        chooseCapability(fixture, 'All capabilities');

        expect(sectionTitles(fixture)).toEqual(['LLM', 'Embeddings', 'Realtime', 'System One']);
    });

    it.each([
        [
            'a Capabilities option with no configs',
            (fixture: ComponentFixture<LlmLibrarySectionComponent>) => chooseCapability(fixture, 'Realtime'),
        ],
        [
            'a search nothing matches',
            (fixture: ComponentFixture<LlmLibrarySectionComponent>) => search(fixture, 'no such config'),
        ],
    ])('says "No configurations match." and keeps Select when %s hides every card', (_case, hideAll) => {
        const { fixture } = render([libraryModel(ModelTypes.LLM, SHARED_ID)], { grantedActions: [ActionCode.Delete] });

        hideAll(fixture);

        expect(sectionTitles(fixture)).toEqual([]);
        expect(emptyHint(fixture)).toBe('No configurations match.');
        expect(selectButton(fixture)).not.toBeNull();
    });

    it('says "No configurations yet." when there are none', () => {
        const { fixture } = render([], { grantedActions: [ActionCode.Delete] });

        expect(emptyHint(fixture)).toBe('No configurations yet.');
    });

    it('drops ticked cards the filter hides from the count and from the delete', () => {
        const llmModel = libraryModel(ModelTypes.LLM, SHARED_ID);
        const embeddingModel = libraryModel(ModelTypes.EMBEDDING, SHARED_ID);
        const { fixture, runBulkDelete } = render([llmModel, embeddingModel], {
            grantedActions: [ActionCode.Delete],
        });
        enterSelectMode(fixture);
        tick(fixture, llmModel);
        tick(fixture, embeddingModel);
        expect(selectLabel(fixture)).toBe('Select (2)');

        chooseCapability(fixture, 'Embedding');

        expect(selectLabel(fixture)).toBe('Select (1)');
        (fixture.nativeElement as HTMLElement)
            .querySelector<HTMLButtonElement>('.header-right > app-button button')!
            .click();
        const groups = runBulkDelete.mock.calls[0][0] as { label: { singular: string }; items: unknown[] }[];
        expect(groups.map((group) => group.label.singular)).toEqual(['embedding config']);
        expect(groups[0].items).toEqual([{ id: SHARED_ID, name: EMBEDDING_CONFIG.custom_name }]);
    });

    it('ends select mode when the search hides every ticked card', () => {
        const llmModel = libraryModel(ModelTypes.LLM, SHARED_ID);
        const embeddingModel = libraryModel(ModelTypes.EMBEDDING, SHARED_ID);
        const { fixture } = render([llmModel, embeddingModel], { grantedActions: [ActionCode.Delete] });
        enterSelectMode(fixture);
        tick(fixture, llmModel);

        search(fixture, embeddingModel.customName);

        expect(fixture.componentInstance.selectMode()).toBe(false);
        expect(selectLabel(fixture)).toBe('Select');
    });

    it('keeps the ticked cards of a collapsed section in the count', () => {
        const llmModel = libraryModel(ModelTypes.LLM, SHARED_ID);
        const { fixture } = render([llmModel], { grantedActions: [ActionCode.Delete] });
        enterSelectMode(fixture);
        tick(fixture, llmModel);

        (fixture.nativeElement as HTMLElement).querySelector<HTMLButtonElement>('.section-toggle')!.click();
        fixture.detectChanges();

        expect(selectLabel(fixture)).toBe('Select (1)');
    });
});
