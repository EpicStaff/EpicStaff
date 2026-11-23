// Pins the collection wizard's step logic (in-flight guard, indexing confirmation) at the unit layer, and which
// container the Configure step renders (graph tabbed view or plain) at the component layer through the DOM.
import { DIALOG_DATA, DialogRef } from '@angular/cdk/dialog';
import { HttpErrorResponse } from '@angular/common/http';
import { Component, input, model, signal } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { ConfirmationDialogService, ConfirmationResult } from '@shared/components';
import { firstValueFrom, Observable, of, Subject, throwError } from 'rxjs';

import { PermissionsService } from '../../../../services/auth/permissions.service';
import { ToastService } from '../../../../services/notifications';
import { IndexingEstimate, RagType } from '../../models/base-rag.model';
import { CollectionStatus, CreateCollectionDtoResponse, CreateCollectionStep } from '../../models/collection.model';
import { DisplayedListDocument } from '../../models/document.model';
import { CollectionDetailsGraphRag } from '../../models/graph-rag.model';
import { CollectionDetailsNaiveRag } from '../../models/naive-rag.model';
import { CollectionsApiService } from '../../services/collections-api.service';
import { CollectionsStorageService } from '../../services/collections-storage.service';
import { IndexingConfirmationDialogService } from '../../services/indexing-confirmation-dialog.service';
import { RagDeleteRegistryService } from '../../services/rag-delete-registry.service';
import { IndexingConfirmationDialogData } from '../indexing-confirmation-dialog/indexing-confirmation-dialog.component';
import { StepSelectRagComponent } from './components/steps/step-select-rag/step-select-rag.component';
import { StepUploadFilesComponent } from './components/steps/step-upload-files/step-upload-files.component';
import { CreateCollectionDialogComponent } from './create-collection-dialog.component';
import { RagCreationStrategy } from './factory/interfaces/rag-creation-strategy.interface';
import { RagStrategyFactory } from './factory/rag-creation.factory';

describe('CreateCollectionDialogComponent in-flight guard', () => {
    it('does not run the step action twice while the first is pending', () => {
        const pending = new Subject<boolean>();
        const create = vi.fn(() => pending);
        TestBed.configureTestingModule({
            providers: [
                { provide: DIALOG_DATA, useValue: { collection_id: 1 } },
                { provide: DialogRef, useValue: { close: vi.fn() } },
                { provide: RagStrategyFactory, useValue: { create: () => ({ create }) } },
                {
                    provide: CollectionsStorageService,
                    useValue: {
                        fullCollections: signal([{ collection_id: 1, rag_configurations: [] }]),
                        getFullCollection: () => of(null),
                    },
                },
                { provide: ToastService, useValue: { error: vi.fn() } },
                { provide: ConfirmationDialogService, useValue: { confirm: vi.fn() } },
                { provide: IndexingConfirmationDialogService, useValue: { confirm: vi.fn() } },
                { provide: RagDeleteRegistryService, useValue: {} },
                { provide: PermissionsService, useValue: { can: () => true } },
            ],
        });
        const component = TestBed.runInInjectionContext(() => new CreateCollectionDialogComponent());
        component.currentStepIndex.set(1);
        component.selectedRagType.set('naive');
        component.selectedEmbedder.set(5);

        component.nextStep();
        component.nextStep();

        expect(create).toHaveBeenCalledTimes(1);
        expect(component.nextDisabled()).toBe(true);

        pending.next(true);
        pending.complete();
        expect(component.isProceeding()).toBe(false);
    });
});

describe('CreateCollectionDialogComponent indexing confirmation', () => {
    const RAG_ID = 11;
    const TIMESTAMPS = { created_at: '2026-03-12T13:28:23Z', updated_at: '2026-03-12T13:28:23Z' };
    const ESTIMATE: IndexingEstimate = {
        rag_type: 'naive',
        document_count: 1,
        chunk_count: 1,
        embedding: { tokens: 10, exact: true, cost_usd: null },
    };
    const COLLECTION: CreateCollectionDtoResponse = {
        ...TIMESTAMPS,
        collection_id: 1,
        collection_name: 'Docs',
        description: '',
        status: CollectionStatus.COMPLETED,
        document_count: 1,
        rag_configurations: [],
        created_by: null,
        last_edited_by: null,
        last_edited_at: null,
    };
    // The RAGs step 2 creates; the server lists them only from then on. Naive and graph ids can be equal.
    const NAIVE_RAG: CollectionDetailsNaiveRag = {
        ...TIMESTAMPS,
        chunks_count: 0,
        document_configs_count: 1,
        embedder_id: 5,
        embedder_name: 'Small embedder',
        embeddings_count: 0,
        indexing_document_config_ids: [],
        is_ready_for_indexing: true,
        message: null,
        rag_id: RAG_ID,
        rag_type: 'naive',
        status: 'new',
        indexing_usage: {},
    };
    const GRAPH_RAG: CollectionDetailsGraphRag = {
        ...TIMESTAMPS,
        embedder_id: '6',
        embedder_name: 'Large embedder',
        llm_name: 'GPT config',
        is_ready_for_indexing: true,
        message: null,
        rag_id: RAG_ID,
        rag_type: 'graph',
        require_reindexing: false,
        reindex_reason: {},
        status: 'new',
        processing_document_ids: [],
        indexing_usage: {},
    };
    const FILE = { configId: 7, fileName: 'a.pdf', wasIndexed: false };

    beforeEach(() => vi.useFakeTimers());
    afterEach(() => vi.useRealTimers());

    /**
     * Walks the wizard from "Select RAG" to the indexing confirmation, which answers `answer`.
     * `reloadedCollection$` is what the server sends when the wizard loads the collection again after the create.
     */
    function openIndexingConfirmation(
        ragType: RagType,
        strategyExtras: object = {},
        answer: ConfirmationResult = false,
        reloadedCollection$: Observable<CreateCollectionDtoResponse> = of({
            ...COLLECTION,
            rag_configurations: [NAIVE_RAG, GRAPH_RAG],
        }),
        configurationExtras: object = {}
    ): {
        shown: IndexingConfirmationDialogData;
        startIndexing: ReturnType<typeof vi.fn>;
        component: CreateCollectionDialogComponent;
    } {
        let shown: IndexingConfirmationDialogData | undefined;
        const startIndexing = vi.fn(() => of(true));
        TestBed.configureTestingModule({
            providers: [
                { provide: DIALOG_DATA, useValue: { collection_id: 1 } },
                { provide: DialogRef, useValue: { close: vi.fn() } },
                {
                    provide: RagStrategyFactory,
                    useValue: {
                        create: () => ({
                            create: () => of(true),
                            canIndex: () => true,
                            getRagId: () => RAG_ID,
                            startIndexing,
                            ...strategyExtras,
                        }),
                    },
                },
                {
                    provide: CollectionsApiService,
                    useValue: { getCollectionById: () => reloadedCollection$ },
                },
                { provide: ToastService, useValue: { error: vi.fn() } },
                { provide: ConfirmationDialogService, useValue: { confirm: vi.fn() } },
                {
                    provide: IndexingConfirmationDialogService,
                    useValue: {
                        confirm: (data: IndexingConfirmationDialogData) => {
                            shown = data;
                            return of(answer);
                        },
                    },
                },
                { provide: RagDeleteRegistryService, useValue: {} },
                { provide: PermissionsService, useValue: { can: () => true } },
            ],
        });
        // The collection as the wizard found it, before any RAG.
        TestBed.inject(CollectionsStorageService).updateOrCreateCollectionInCache(COLLECTION);
        const component = TestBed.runInInjectionContext(() => new CreateCollectionDialogComponent());
        const instance = {
            getConfigurationData: () => ({}),
            getIndexingDocuments: () => [FILE],
            ...configurationExtras,
        };
        Reflect.set(component, 'strategyComponent', { _componentRef: { instance } });
        component.currentStepIndex.set(1);
        component.selectedRagType.set(ragType);
        component.selectedEmbedder.set(5);
        component.selectedLLM.set(3);

        component.nextStep();
        // Loading the collection again after the create has a short built-in delay.
        vi.advanceTimersByTime(300);
        component.nextStep();

        return { shown: shown!, startIndexing, component };
    }

    it.each<[RagType, Pick<IndexingConfirmationDialogData, 'embedderName' | 'llmName'>]>([
        ['naive', { embedderName: 'Small embedder', llmName: null }],
        ['graph', { embedderName: 'Large embedder', llmName: 'GPT config' }],
    ])('names the models of the %s RAG it just created', (ragType, names) => {
        const { shown } = openIndexingConfirmation(ragType);

        expect(shown).toEqual({ documents: [FILE], ragType, estimate$: undefined, ...names });
    });

    it('still moves to Configure, without model names, when loading the collection again fails', () => {
        const { shown, component } = openIndexingConfirmation(
            'naive',
            {},
            false,
            throwError(() => new Error('network down'))
        );

        expect(component.currentStep().id).toBe(CreateCollectionStep.CONFIGURE);
        expect(shown).toEqual({
            documents: [FILE],
            ragType: 'naive',
            estimate$: undefined,
            embedderName: null,
            llmName: null,
        });
    });

    it('opens with the estimate for the files to index when the strategy can estimate', async () => {
        // A fake that only knows the estimate for the file being indexed (config 7).
        const estimateIndexing = (configIds: number[]) => of(configIds.join() === '7' ? ESTIMATE : null);
        const { shown } = openIndexingConfirmation('naive', { estimateIndexing });

        await expect(firstValueFrom(shown.estimate$!)).resolves.toEqual(ESTIMATE);
    });

    it.each<[ConfirmationResult, number]>([
        [true, 1],
        [false, 0],
        ['close', 0],
    ])('starts indexing only when the confirmation answers true (answer %s)', (answer, startCount) => {
        const { startIndexing } = openIndexingConfirmation('naive', {}, answer);

        expect(startIndexing).toHaveBeenCalledTimes(startCount);
    });

    it.each<[string, object]>([
        ['a configuration with no fields', {}],
        [
            'a configuration with no such field',
            { setServerValidationErrors: () => undefined, showsServerErrorsInline: () => false },
        ],
    ])('says in a toast why indexing was refused when %s cannot show the error', (_case, configurationExtras) => {
        const refusal = new HttpErrorResponse({
            status: 400,
            error: {
                type: 'validation_error',
                errors: [{ code: 'invalid', detail: 'Unknown document.', attr: 'document_ids', context: null }],
            },
        });

        openIndexingConfirmation(
            'naive',
            { startIndexing: () => throwError(() => refusal) },
            true,
            undefined,
            configurationExtras
        );

        expect(TestBed.inject(ToastService).error).toHaveBeenCalledWith('document_ids: Unknown document.');
    });
});

describe('CreateCollectionDialogComponent graph tabs', () => {
    const GRAPH_RAG_ID = 42;
    const VALID_DOCUMENT: DisplayedListDocument = {
        document_id: 1,
        file_name: 'a.pdf',
        file_size: 10,
        source_collection: 1,
        isValidType: true,
        isValidSize: true,
    };

    /** Stands in for the upload step (file picker, uploads): "Add file" selects one valid document. */
    @Component({
        selector: 'app-step-upload-files',
        template: `<button
            type="button"
            (click)="documents.set([document])"
        >
            Add file
        </button>`,
    })
    class StepUploadFilesStubComponent {
        readonly collection = input<unknown>();
        readonly initialDocumentId = input<number | undefined>();
        readonly documents = model<DisplayedListDocument[]>([]);
        readonly document = VALID_DOCUMENT;
    }

    /** Stands in for the RAG picker (model lists, selects): one button per RAG type, one that picks the models. */
    @Component({
        selector: 'app-step-select-rag',
        template: `
            <button
                type="button"
                (click)="selectedRag.set('graph')"
            >
                Graph RAG
            </button>
            <button
                type="button"
                (click)="selectedRag.set('naive')"
            >
                Naive RAG
            </button>
            <button
                type="button"
                (click)="selectedEmbedder.set(5); selectedLLM.set(3)"
            >
                Pick models
            </button>
        `,
    })
    class StepSelectRagStubComponent {
        readonly collection = input<unknown>();
        readonly selectedRag = model<RagType | null>(null);
        readonly selectedEmbedder = model<number | null>(null);
        readonly selectedLLM = model<number | null>(null);
    }

    /** What the strategy hands the Configure step to render. */
    @Component({ selector: 'app-configuration-stub', template: 'Configuration form' })
    class ConfigurationStubComponent {}

    // jsdom has no ResizeObserver; the shared overflow directives in the dialog header only need it to exist.
    class ResizeObserverStub {
        observe(): void {}
        unobserve(): void {}
        disconnect(): void {}
    }

    let fixture: ComponentFixture<CreateCollectionDialogComponent>;

    beforeEach(() => vi.stubGlobal('ResizeObserver', ResizeObserverStub));
    afterEach(() => vi.unstubAllGlobals());

    function render(ragId: number | null = GRAPH_RAG_ID): void {
        const strategy: RagCreationStrategy = {
            canIndex: signal(false),
            isIndexing: signal(false),
            create: () => of(true),
            getRagId: () => ragId,
            startIndexing: () => of(true),
            stopIndexing: () => of(true),
            getConfigurationComponent: () => ConfigurationStubComponent,
            getConfigurationInputs: () => ({}),
            dispose: () => undefined,
        };
        TestBed.configureTestingModule({
            imports: [CreateCollectionDialogComponent],
            providers: [
                { provide: DIALOG_DATA, useValue: { collection_id: 1 } },
                { provide: DialogRef, useValue: { close: vi.fn() } },
                { provide: RagStrategyFactory, useValue: { create: () => strategy } },
                {
                    provide: CollectionsStorageService,
                    useValue: {
                        fullCollections: signal([{ collection_id: 1, rag_configurations: [] }]),
                        getFullCollection: () => of(null),
                        // Never indexed: the tabbed view shows the configuration content, not the graph tabs' content.
                        getRagIndexingUsage: () => null,
                    },
                },
                { provide: ToastService, useValue: { error: vi.fn() } },
                { provide: ConfirmationDialogService, useValue: { confirm: vi.fn() } },
                { provide: IndexingConfirmationDialogService, useValue: { confirm: vi.fn() } },
                { provide: RagDeleteRegistryService, useValue: {} },
                { provide: PermissionsService, useValue: { can: () => true } },
            ],
        });
        TestBed.overrideComponent(CreateCollectionDialogComponent, {
            remove: { imports: [StepUploadFilesComponent, StepSelectRagComponent] },
            add: { imports: [StepUploadFilesStubComponent, StepSelectRagStubComponent] },
        });
        fixture = TestBed.createComponent(CreateCollectionDialogComponent);
        fixture.detectChanges();
    }

    function clickButton(text: string): void {
        const button = Array.from((fixture.nativeElement as HTMLElement).querySelectorAll('button')).find(
            (candidate) => candidate.textContent?.trim() === text
        );
        expect(button, `button "${text}"`).toBeDefined();
        button!.click();
        fixture.detectChanges();
    }

    /** Upload a file, then pick the RAG type and models on "Select RAG"; `proceed` also clicks Next to Configure. */
    function walkToSelectRag(ragButton: string, proceed: boolean): void {
        clickButton('Add file');
        clickButton('Next');
        clickButton(ragButton);
        clickButton('Pick models');
        if (proceed) clickButton('Next');
    }

    function tabbedView(): HTMLElement | null {
        return (fixture.nativeElement as HTMLElement).querySelector('app-graph-rag-tabbed-view');
    }

    function configurationForm(): HTMLElement | null {
        return (fixture.nativeElement as HTMLElement).querySelector('app-configuration-stub');
    }

    it('wraps the Configure step of a created graph RAG in the graph tabbed view', () => {
        render();
        walkToSelectRag('Graph RAG', true);

        expect(tabbedView()).not.toBeNull();
        expect(tabbedView()!.querySelector('app-configuration-stub')).not.toBeNull();
    });

    it('does not show the tabbed view on "Select RAG", before the graph RAG exists', () => {
        render();
        walkToSelectRag('Graph RAG', false);

        expect(tabbedView()).toBeNull();
    });

    it('shows a naive RAG configuration without the graph tabbed view', () => {
        render();
        walkToSelectRag('Naive RAG', true);

        expect(tabbedView()).toBeNull();
        expect(configurationForm()).not.toBeNull();
    });

    it('shows the configuration without the tabbed view while the graph strategy has no RAG id', () => {
        render(null);
        walkToSelectRag('Graph RAG', true);

        expect(tabbedView()).toBeNull();
        expect(configurationForm()).not.toBeNull();
    });
});
