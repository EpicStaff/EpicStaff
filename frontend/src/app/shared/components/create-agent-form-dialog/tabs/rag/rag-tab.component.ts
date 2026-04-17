import { ChangeDetectionStrategy, Component, computed, DestroyRef, inject, input, OnInit, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { FormBuilder, FormControl, FormGroup, ReactiveFormsModule, Validators } from '@angular/forms';
import {
    DualSliderComponent,
    InputNumberComponent,
    RadioButtonComponent,
    SelectComponent,
    SelectItem,
    SliderWithStepperComponent,
    TextareaComponent,
    ValidationErrorsComponent,
} from '@shared/components';

import {
    GetCollectionRagsResponse,
    GetCollectionRequest,
} from '../../../../../features/knowledge-sources/models/collection.model';
import { AgentRag } from '../../../../../features/staff/models/agent.model';
import { AgentSearchConfigs, GraphBasicSearchConfig, GraphLocalSearchConfig } from '../../../../models';

@Component({
    selector: 'app-rag-tab',
    templateUrl: './rag-tab.component.html',
    styleUrls: ['../tab.component.scss'],
    imports: [
        ReactiveFormsModule,
        SelectComponent,
        SliderWithStepperComponent,
        RadioButtonComponent,
        InputNumberComponent,
        DualSliderComponent,
        TextareaComponent,
        ValidationErrorsComponent,
    ],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class RagTabComponent implements OnInit {
    private fb = inject(FormBuilder);
    private destroyRef = inject(DestroyRef);

    form = input.required<FormGroup>();
    allKnowledgeSources = input.required<GetCollectionRequest[]>();
    agentRags = input.required<GetCollectionRagsResponse[]>();
    searchConfigs = input.required<AgentSearchConfigs | null>();
    loadingKnowledgeSources = input<boolean>(false);
    loadingRags = input<boolean>(false);

    selectedRagType = signal<'naive' | 'graph' | null>(null);

    knowledgeSelectItems = computed<SelectItem[]>(() => {
        return [
            {
                name: 'No collection',
                value: null,
            },
            ...this.allKnowledgeSources().map((item) => ({
                name: item.collection_name,
                value: item.collection_id,
            })),
        ];
    });
    agentRagSelectItems = computed<SelectItem<AgentRag>[]>(() => {
        return this.agentRags().map((item) => ({
            name: item.rag_type,
            value: {
                rag_id: item.rag_id,
                rag_type: item.rag_type,
            },
        }));
    });

    searchConfigsFormGroup: FormGroup | null = null;
    searchTypes: SelectItem[] = [
        {
            name: 'Basic',
            value: 'basic',
        },
        {
            name: 'Local',
            value: 'local',
        },
        {
            name: 'Global',
            value: 'global',
        },
        {
            name: 'DRIFT',
            value: 'drift',
        },
    ];

    textUnitProportionControl!: FormControl;
    communityProportionControl!: FormControl;

    ngOnInit() {
        const ragControl = this.form().get('rag');
        const ragControlValue = ragControl?.value;

        if (ragControlValue) {
            this.selectedRagType.set(ragControlValue.rag_type);
            this.initSearchConfigsFormGroup(ragControlValue.rag_type);
        }

        ragControl?.valueChanges.pipe(takeUntilDestroyed(this.destroyRef)).subscribe((rag) => {
            if (!rag) {
                this.searchConfigsFormGroup = null;
                return;
            }
            this.selectedRagType.set(rag.rag_type);
            this.initSearchConfigsFormGroup(rag.rag_type);
        });
    }

    private initSearchConfigsFormGroup(ragType: string): void {
        const configs = this.searchConfigs();
        if (ragType === 'naive') {
            this.searchConfigsFormGroup = this.fb.group({
                search_limit: [configs?.naive?.search_limit ?? 3, [Validators.min(1), Validators.max(1000)]],
                similarity_threshold: [
                    configs?.naive?.similarity_threshold ?? 0.2,
                    [Validators.min(0.0), Validators.max(1.0)],
                ],
            });
        }

        if (ragType === 'graph') {
            this.searchConfigsFormGroup = this.fb.group({
                search_method: [configs?.graph?.search_method ?? 'basic', [Validators.required]],
                basic: this.initGraphBasicSearchConfig(configs?.graph?.basic),
                local: this.initGraphLocalSearchConfig(configs?.graph?.local),
            });
        }

        this.form().setControl('search_configs', this.searchConfigsFormGroup);
    }

    private initGraphBasicSearchConfig(configs: GraphBasicSearchConfig | undefined): FormGroup {
        return this.fb.group({
            prompt: [configs?.prompt || null, [Validators.maxLength(1000)]],
            k: [configs?.k ?? 10, [Validators.required, Validators.min(1), Validators.max(100)]],
            max_context_tokens: [
                configs?.max_context_tokens ?? 12000,
                [Validators.required, Validators.min(100), Validators.max(100000)],
            ],
        });
    }

    private initGraphLocalSearchConfig(configs: GraphLocalSearchConfig | undefined): FormGroup {
        this.textUnitProportionControl = this.fb.control(configs?.text_unit_prop ?? 0.5, [
            Validators.required,
            Validators.min(0),
            Validators.max(1),
        ]);

        this.communityProportionControl = this.fb.control(configs?.community_prop ?? 0.15, [
            Validators.required,
            Validators.min(0),
            Validators.max(1),
        ]);

        return this.fb.group({
            prompt: [configs?.prompt || null, [Validators.maxLength(1000)]],
            text_unit_prop: this.textUnitProportionControl,
            community_prop: this.communityProportionControl,
            conversation_history_max_turns: [
                configs?.conversation_history_max_turns ?? 5,
                [Validators.required, Validators.min(1), Validators.max(50)],
            ],
            max_context_tokens: [
                configs?.max_context_tokens ?? 100,
                [Validators.required, Validators.min(100), Validators.max(100000)],
            ],
            top_k_entities: [
                configs?.top_k_entities ?? 10,
                [Validators.required, Validators.min(1), Validators.max(100)],
            ],
            top_k_relationships: [
                configs?.top_k_relationships ?? 10,
                [Validators.required, Validators.min(1), Validators.max(100)],
            ],
        });
    }

    onTextUnitPropUpdate(value: number): void {
        this.textUnitProportionControl.setValue(value);
    }

    onCommunityPropUpdate(value: number): void {
        this.communityProportionControl.setValue(value);
    }

    isKnowledgeControlInvalid(): boolean {
        return !!this.form().get('knowledge_collection')?.invalid;
    }

    isRagControlInvalid(): boolean {
        return !!this.form().get('rag')?.invalid;
    }
}
