import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';

import { AgentDefinition } from '../models/agent-definition.model';
import { AgentDefinitionsApiService } from './agent-definitions-api.service';

const SOURCE: AgentDefinition = {
    id: 3,
    org: 1,
    name: 'CV Processor',
    description: '',
    instructions: '',
    instruction_list: [],
    llm_config: 1,
    fallback_llm_config: 2,
    fcm_llm_config: null,
    agent_definition_realtime_config_id: null,
    has_realtime_definition: false,
    default_surfaces: [],
    metadata: {},
    max_iter: 20,
    max_rpm: 10,
    max_execution_time: 60,
    cache: true,
    max_retry_limit: 2,
    default_temperature: 0.7,
    max_tool_calls: 15,
    tool_timeout: 300,
    max_consecutive_failures: 3,
    schema_max_retries: 2,
    created_at: null,
    created_by: null,
    last_edited_by: null,
    last_edited_at: null,
};

describe('AgentDefinitionsApiService.copy', () => {
    it('creates the copy with the same primary and fallback LLM config', () => {
        TestBed.configureTestingModule({ providers: [provideHttpClient(), provideHttpClientTesting()] });
        const http = TestBed.inject(HttpTestingController);

        TestBed.inject(AgentDefinitionsApiService).copy(SOURCE, 'CV Processor (copy)').subscribe();

        const request = http.expectOne((req) => req.method === 'POST');
        expect(request.request.body).toMatchObject({ llm_config: 1, fallback_llm_config: 2 });
        http.verify();
    });
});
