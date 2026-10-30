import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';

import { ConfigService } from '../../../services/config';
import { AgentDefinition } from '../models/agent-definition.model';
import { AgentsPageStore } from './agents-page-store.service';
import { SurfaceCatalogsStore } from './surface-catalogs-store.service';

const AGENTS_URL = '/api/agent-definitions/';
const SURFACES_URL = '/api/surfaces/';

function agentOf(id: number, name: string): AgentDefinition {
    return {
        id,
        org: 1,
        name,
        description: '',
        instructions: '',
        instruction_list: [],
        llm_config: null,
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
        created_at: '2026-10-29T09:00:00Z',
        created_by: { id: 1, display_name: 'Ivan Bohun', avatar_url: null },
        last_edited_by: null,
        last_edited_at: null,
    };
}

describe('AgentsPageStore: whether the agent shown is the one the latest draft was saved as', () => {
    let store: AgentsPageStore;
    let backend: HttpTestingController;

    beforeEach(() => {
        TestBed.configureTestingModule({
            providers: [
                provideHttpClient(),
                provideHttpClientTesting(),
                { provide: ConfigService, useValue: { apiUrl: '/api/' } as unknown as ConfigService },
                AgentsPageStore,
                // Only reloaded after a failed surface save, which these tests never make.
                { provide: SurfaceCatalogsStore, useValue: {} },
            ],
        });
        store = TestBed.inject(AgentsPageStore);
        backend = TestBed.inject(HttpTestingController);
    });

    afterEach(() => backend.verify());

    function loadAgents(agents: AgentDefinition[]): void {
        store.load();
        backend
            .expectOne((request) => request.method === 'GET' && request.url === AGENTS_URL)
            .flush({ count: agents.length, next: null, previous: null, results: agents });
        backend
            .expectOne((request) => request.method === 'GET' && request.url === SURFACES_URL)
            .flush({ count: 0, next: null, previous: null, results: [] });
    }

    /** Add Agent, then a name: the backend creates the agent. */
    function createFromDraft(agent: AgentDefinition): void {
        store.beginCreateAgent();
        store.saveNewAgent({ name: agent.name });
        backend.expectOne({ method: 'POST', url: AGENTS_URL }).flush(agent);
    }

    it('is false while drafting, and true once the draft is saved and its agent is shown', () => {
        store.beginCreateAgent();
        expect(store.isSelectedAgentFromLatestDraft()).toBe(false);

        store.saveNewAgent({ name: 'CV Processor' });
        backend.expectOne({ method: 'POST', url: AGENTS_URL }).flush(agentOf(7, 'CV Processor'));

        expect(store.selectedAgent()?.id).toBe(7);
        expect(store.isSelectedAgentFromLatestDraft()).toBe(true);
    });

    it('stays false when the create fails, and the draft stays open to fix the name', () => {
        store.beginCreateAgent();

        store.saveNewAgent({ name: 'CV Processor' });
        backend
            .expectOne({ method: 'POST', url: AGENTS_URL })
            .flush({ name: ['Invalid name.'] }, { status: 400, statusText: 'Bad Request' });

        expect(store.isDraftingAgent()).toBe(true);
        expect(store.isSelectedAgentFromLatestDraft()).toBe(false);
    });

    it('is false for an agent that was there before', () => {
        loadAgents([agentOf(3, 'Invoice Reader')]);
        createFromDraft(agentOf(7, 'CV Processor'));

        store.selectAgent(3);

        expect(store.isSelectedAgentFromLatestDraft()).toBe(false);
    });

    it('is false for the agent of an earlier draft once another draft begins, saved or not', () => {
        createFromDraft(agentOf(7, 'CV Processor'));

        store.beginCreateAgent();
        store.cancelDraft();
        store.selectAgent(7);

        expect(store.isSelectedAgentFromLatestDraft()).toBe(false);
    });
});
