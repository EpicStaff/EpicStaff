import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';

import { ConfigService } from '../../../services/config';
import { AgentDefinition } from '../models/agent-definition.model';
import { AgentDefinitionsApiService } from './agent-definitions-api.service';

const SOURCE: AgentDefinition = {
    id: 3,
    org: 1,
    name: 'CV Processor',
    group: null,
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
    it('asks the server to copy the agent, sending no fields of its own', () => {
        TestBed.configureTestingModule({
            providers: [
                provideHttpClient(),
                provideHttpClientTesting(),
                { provide: ConfigService, useValue: { apiUrl: '/api/' } as unknown as ConfigService },
            ],
        });
        const http = TestBed.inject(HttpTestingController);
        let copied: AgentDefinition | undefined;

        TestBed.inject(AgentDefinitionsApiService)
            .copy(3)
            .subscribe((agent) => (copied = agent));

        const request = http.expectOne({ method: 'POST', url: '/api/agent-definitions/3/copy/' });
        expect(request.request.body).toEqual({});
        request.flush({ ...SOURCE, id: 8, name: 'CV Processor #2' }, { status: 201, statusText: 'Created' });
        expect(copied?.id).toBe(8);
        http.verify();
    });
});
