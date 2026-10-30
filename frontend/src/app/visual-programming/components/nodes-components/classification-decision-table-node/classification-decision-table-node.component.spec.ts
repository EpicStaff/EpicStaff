import { signal } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { LlmConfigStorageService, SystemOneConfigStorageService } from '@shared/services';
import { of } from 'rxjs';

import { PromptConfig } from '../../../core/models/classification-decision-table.model';
import { ClassificationDecisionTableNodeModel } from '../../../core/models/node.model';
import { FlowService } from '../../../services/flow.service';
import { FlowReadOnlyService } from '../../../services/flow-readonly.service';
import { FlowSettingsService } from '../../../services/flow-settings.service';
import { ClassificationDecisionTableNodeComponent } from './classification-decision-table-node.component';

const SYSTEM_ONE_MESSAGE = 'A System One entry needs a config';
const LLM_MESSAGE = 'LLM config is missing or was deleted';

describe('ClassificationDecisionTableNodeComponent config warnings', () => {
    const systemOneConfigs = signal<{ id: number }[]>([]);
    const systemOneLoaded = signal(false);

    function nodeWith(prompts: Record<string, PromptConfig>): ClassificationDecisionTableNodeModel {
        return {
            data: { table: { prompts, condition_groups: [], default_llm_config: null } },
        } as unknown as ClassificationDecisionTableNodeModel;
    }

    function llmPrompt(llmConfig: number | null): PromptConfig {
        return {
            prompt_text: 'Classify',
            llm_config: llmConfig,
            output_schema: null,
            result_variable: 'category',
            variable_mappings: {},
        };
    }

    function systemOnePrompt(config: number | null): PromptConfig {
        return { ...llmPrompt(null), kind: 'system_one', system_one_config: config };
    }

    function messagesFor(prompts: Record<string, PromptConfig>): string[] {
        const component = TestBed.runInInjectionContext(() => new ClassificationDecisionTableNodeComponent());
        component.node = nodeWith(prompts);
        return component.errorMessages;
    }

    beforeEach(() => {
        systemOneConfigs.set([{ id: 7 }]);
        systemOneLoaded.set(true);
        TestBed.configureTestingModule({
            providers: [
                { provide: FlowService, useValue: {} },
                { provide: FlowReadOnlyService, useValue: { isReadOnly: signal(false) } },
                { provide: FlowSettingsService, useValue: {} },
                {
                    provide: LlmConfigStorageService,
                    useValue: {
                        getAllConfigs: () => of([]),
                        configs: signal([{ id: 2 }]),
                        isConfigsLoaded: signal(true),
                    },
                },
                {
                    provide: SystemOneConfigStorageService,
                    useValue: {
                        getAllConfigs: () => of([]),
                        configs: systemOneConfigs,
                        isConfigsLoaded: systemOneLoaded,
                    },
                },
            ],
        });
    });

    it('warns about a System One entry with no config', () => {
        expect(messagesFor({ check: systemOnePrompt(null) })).toEqual([SYSTEM_ONE_MESSAGE]);
    });

    it('does not warn about a System One entry whose config exists', () => {
        expect(messagesFor({ check: systemOnePrompt(7) })).toEqual([]);
    });

    it('warns about a System One entry whose config was deleted', () => {
        expect(messagesFor({ check: systemOnePrompt(8) })).toEqual([SYSTEM_ONE_MESSAGE]);
    });

    it('does not call a System One config deleted before the configs have loaded', () => {
        systemOneLoaded.set(false);
        systemOneConfigs.set([]);

        expect(messagesFor({ check: systemOnePrompt(8) })).toEqual([]);
    });

    it('never raises the LLM warning for a System One entry', () => {
        expect(messagesFor({ check: systemOnePrompt(7) })).not.toContain(LLM_MESSAGE);
    });

    it('still raises the LLM warning for an LLM prompt with no LLM', () => {
        expect(messagesFor({ check: llmPrompt(null) })).toEqual([LLM_MESSAGE]);
    });
});
