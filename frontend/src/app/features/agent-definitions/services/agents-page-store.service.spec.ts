import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { signal } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { LabelColor, LabelDto } from '@shared/models';
import { of } from 'rxjs';

import { PermissionsService } from '../../../services/auth/permissions.service';
import { ProfileService } from '../../../services/auth/profile.service';
import { ConfigService } from '../../../services/config';
import { ToastService } from '../../../services/notifications';
import { AgentDefinition, CreateAgentDefinitionRequest } from '../models/agent-definition.model';
import { Surface } from '../models/surface.model';
import { BranchTreeNode, ExplorerGroupBlock } from '../models/tree-node.model';
import { AgentDefinitionsApiService } from './agent-definitions-api.service';
import { AgentGroupsApiService } from './agent-groups-api.service';
import { AgentsPageStore } from './agents-page-store.service';
import { SurfaceCatalogsStore } from './surface-catalogs-store.service';
import { SurfacesApiService } from './surfaces-api.service';

const SALES = 1;
const SUPPORT = 2;
const LEGAL = 3;

function group(id: number, name: string): LabelDto {
    return { id, name, parent: null, full_path: name, created_at: '', metadata: { color: LabelColor.Blue } };
}

function agent(id: number, name: string, groupId: number | null, ownedSurfaceIds: number[] = []): AgentDefinition {
    return {
        id,
        name,
        group: groupId,
        instruction_list: [],
        default_surfaces: ownedSurfaceIds.map((surface) => ({ surface, place: 'all' as const })),
    } as Partial<AgentDefinition> as AgentDefinition;
}

function surface(id: number, name: string, groupId: number | null, ownerAgentId: number | null = null): Surface {
    return { id, name, group: groupId, owner_agent: ownerAgentId } as Partial<Surface> as Surface;
}

/**
 * The real store over fake HTTP edges, loaded with the given rows. Like the API, PATCH and POST answer
 * with the saved row, and a group DELETE succeeds.
 */
function loadStore(rows: { agents: AgentDefinition[]; surfaces?: Surface[]; groups?: LabelDto[] }): AgentsPageStore {
    const surfaces = rows.surfaces ?? [];
    TestBed.configureTestingModule({
        providers: [
            AgentsPageStore,
            {
                provide: AgentDefinitionsApiService,
                useValue: {
                    getAgentDefinitions: () => of(rows.agents),
                    partialUpdate: (id: number, body: Partial<AgentDefinition>) =>
                        of({ ...rows.agents.find((row) => row.id === id)!, ...body }),
                    create: (body: CreateAgentDefinitionRequest) => of(agent(99, body.name, body.group ?? null)),
                },
            },
            {
                provide: SurfacesApiService,
                useValue: {
                    getSurfaces: () => of(surfaces),
                    partialUpdate: (id: number, body: Partial<Surface>) =>
                        of({ ...surfaces.find((row) => row.id === id)!, ...body }),
                },
            },
            {
                provide: AgentGroupsApiService,
                useValue: { getLabels: () => of(rows.groups ?? []), deleteLabel: () => of(undefined) },
            },
            { provide: PermissionsService, useValue: { can: () => true } },
            { provide: ProfileService, useValue: { currentUserSignal: signal({ id: 7 }) } },
            { provide: ToastService, useValue: { success: () => undefined, error: () => undefined } },
            { provide: SurfaceCatalogsStore, useValue: {} },
        ],
    });
    const store = TestBed.inject(AgentsPageStore);
    store.load();
    return store;
}

const labels = (nodes: BranchTreeNode[]): string[] => nodes.map((node) => node.label);

/** Each block as `<group>: <row>, <row>` — enough to see order and membership at a glance. */
const outline = (blocks: ExplorerGroupBlock[] | null): string[] | null =>
    blocks?.map((block) => `${block.label}: ${labels(block.nodes).join(', ')}`) ?? null;

describe('AgentsPageStore group blocks', () => {
    beforeEach(() => localStorage.clear());
    afterEach(() => localStorage.clear());

    it('keeps the flat tree, with no blocks, while the org has no groups', () => {
        const store = loadStore({
            agents: [agent(1, 'Zed', null), agent(2, 'Alpha', null)],
            surfaces: [surface(10, 'Web search', null)],
        });

        expect(store.agentGroupBlocks()).toBeNull();
        expect(store.surfaceGroupBlocks()).toBeNull();
        expect(labels(store.agentsTree())).toEqual(['Zed', 'Alpha']);
        expect(labels(store.surfacesTree())).toEqual(['Web search']);
    });

    it('buckets agents into groups sorted by name, with Ungrouped last', () => {
        const store = loadStore({
            agents: [
                agent(1, 'Lead qualifier', SALES),
                agent(2, 'Draft bot', null),
                agent(3, 'Tier-1 bot', SUPPORT),
                agent(4, 'Deal desk', SALES),
            ],
            groups: [group(SUPPORT, 'Support'), group(SALES, 'Sales')],
        });

        expect(outline(store.agentGroupBlocks())).toEqual([
            'Sales: Lead qualifier, Deal desk',
            'Support: Tier-1 bot',
            'Ungrouped: Draft bot',
        ]);
    });

    it('lists an empty group and an empty Ungrouped in the Agents section, so both can be dropped onto', () => {
        const store = loadStore({
            agents: [agent(1, 'Lead qualifier', SALES)],
            groups: [group(SALES, 'Sales'), group(LEGAL, 'Legal')],
        });

        const counts = store
            .agentGroupBlocks()
            ?.map((block) => ({ label: block.label, memberCount: block.memberCount }));

        expect(counts).toEqual([
            { label: 'Legal', memberCount: 0 },
            { label: 'Sales', memberCount: 1 },
            { label: 'Ungrouped', memberCount: 0 },
        ]);
    });

    it('shows an agent whose group no longer exists once, under Ungrouped', () => {
        const store = loadStore({
            agents: [agent(1, 'Orphan', 99)],
            groups: [group(SALES, 'Sales')],
        });

        expect(outline(store.agentGroupBlocks())).toEqual(['Sales: ', 'Ungrouped: Orphan']);
    });

    it('lists only the groups holding a shared surface in the Shared Surfaces section', () => {
        const store = loadStore({
            agents: [agent(1, 'Tier-1 bot', SUPPORT)],
            surfaces: [surface(10, 'CRM access', SALES), surface(11, 'Web search', null)],
            groups: [group(SALES, 'Sales'), group(SUPPORT, 'Support')],
        });

        expect(outline(store.surfaceGroupBlocks())).toEqual(['Sales: CRM access', 'Ungrouped: Web search']);
    });

    it('never groups an owned surface: it stays under its agent', () => {
        const store = loadStore({
            agents: [agent(1, 'Lead qualifier', SALES, [12])],
            surfaces: [surface(10, 'CRM access', SALES), surface(12, 'Qualify in chat', SALES, 1)],
            groups: [group(SALES, 'Sales')],
        });

        expect(outline(store.surfaceGroupBlocks())).toEqual(['Sales: CRM access', 'Ungrouped: ']);
        const [leadQualifier] = store.agentGroupBlocks()![0].nodes;
        const ownSurfaces =
            leadQualifier.kind === 'agent'
                ? leadQualifier.children.find((child) => child.label === 'Surfaces')
                : undefined;
        expect(ownSurfaces?.kind === 'group' ? labels(ownSurfaces.children) : []).toEqual(['Qualify in chat']);
    });

    it.each<[string, string, string[]]>([
        ['a group name shows the whole group', 'sup', ['Support: Tier-1 bot, Refund checker']],
        ['an agent name shows the agent under its group', 'refund', ['Support: Refund checker']],
        ['an ungrouped agent stays under Ungrouped', 'draft', ['Ungrouped: Draft bot']],
        ['nothing leaves no blocks', 'nomatch', []],
    ])('searching for %s', (_description, query, expected) => {
        const store = loadStore({
            agents: [
                agent(1, 'Lead qualifier', SALES),
                agent(2, 'Tier-1 bot', SUPPORT),
                agent(3, 'Refund checker', SUPPORT),
                agent(4, 'Draft bot', null),
            ],
            groups: [group(SALES, 'Sales'), group(SUPPORT, 'Support')],
        });

        store.setSearch(query);

        expect(outline(store.agentGroupBlocks())).toEqual(expected);
    });
});

/** Each agent and surface as `<name>: <group id>`. */
const membership = (store: AgentsPageStore): string[] => [
    ...store.agents().map((row) => `${row.name}: ${row.group}`),
    ...store.surfaces().map((row) => `${row.name}: ${row.group}`),
];

describe('AgentsPageStore moveSelectionToGroup (the breadcrumb group crumb)', () => {
    afterEach(() => vi.useRealTimers());

    it.each<[string, (store: AgentsPageStore) => void, string[]]>([
        [
            'an agent moves the agent',
            (store) => store.selectAgent(1),
            ['Lead qualifier: 2', 'CRM access: null', 'Qualify in chat: null'],
        ],
        [
            "an agent's instruction moves the agent",
            (store) => store.selectAgentDoc(1, 0),
            ['Lead qualifier: 2', 'CRM access: null', 'Qualify in chat: null'],
        ],
        [
            'an owned surface moves its agent',
            (store) => store.selectSurface(12, 1),
            ['Lead qualifier: 2', 'CRM access: null', 'Qualify in chat: null'],
        ],
        [
            'a shared surface opened under an agent moves that agent',
            (store) => store.selectSurface(10, 1),
            ['Lead qualifier: 2', 'CRM access: null', 'Qualify in chat: null'],
        ],
        [
            'a shared surface moves the surface',
            (store) => store.selectSurface(10),
            ['Lead qualifier: null', 'CRM access: 2', 'Qualify in chat: null'],
        ],
    ])('with %s open', (_description, open, expected) => {
        vi.useFakeTimers();
        const leadQualifier = agent(1, 'Lead qualifier', null, [12]);
        leadQualifier.instruction_list = [{ name: 'Qualify', content: 'Qualify leads' }];
        const store = loadStore({
            agents: [leadQualifier],
            surfaces: [surface(10, 'CRM access', null), surface(12, 'Qualify in chat', null, 1)],
            groups: [group(SALES, 'Sales'), group(SUPPORT, 'Support')],
        });
        open(store);

        store.moveSelectionToGroup(SUPPORT);
        // Surface edits are sent debounced.
        vi.advanceTimersByTime(1000);

        expect(membership(store)).toEqual(expected);
    });
});

describe('AgentsPageStore deleteGroup', () => {
    beforeEach(() => localStorage.clear());
    afterEach(() => localStorage.clear());

    function storeWithSalesAndSupport(): AgentsPageStore {
        return loadStore({
            agents: [agent(1, 'Lead qualifier', SALES), agent(2, 'Tier-1 bot', SUPPORT)],
            surfaces: [surface(10, 'CRM access', SALES)],
            groups: [group(SALES, 'Sales'), group(SUPPORT, 'Support')],
        });
    }

    it('ungroups the members of the deleted group only', () => {
        const store = storeWithSalesAndSupport();

        store.deleteGroup(SALES);

        expect(membership(store)).toEqual(['Lead qualifier: null', 'Tier-1 bot: 2', 'CRM access: null']);
        expect(outline(store.agentGroupBlocks())).toEqual(['Support: Tier-1 bot', 'Ungrouped: Lead qualifier']);
    });

    it("forgets the deleted group's collapsed state and keeps the others'", () => {
        const store = storeWithSalesAndSupport();
        store.toggleGroupCollapsed('agents', SALES);
        store.toggleGroupCollapsed('surfaces', SALES);
        store.toggleGroupCollapsed('agents', SUPPORT);

        store.deleteGroup(SALES);

        expect([
            store.isGroupCollapsed('agents', SALES),
            store.isGroupCollapsed('surfaces', SALES),
            store.isGroupCollapsed('agents', SUPPORT),
        ]).toEqual([false, false, true]);
    });

    it.each([
        { draftGroup: SALES, savedGroup: null },
        { draftGroup: SUPPORT, savedGroup: SUPPORT },
    ])(
        'a new agent drafted into group $draftGroup is saved into $savedGroup after Sales is deleted',
        ({ draftGroup, savedGroup }) => {
            const store = storeWithSalesAndSupport();
            store.beginCreateAgent(draftGroup);

            store.deleteGroup(SALES);
            store.saveNewAgent({ name: 'Closer' });

            expect(store.agents().find((row) => row.name === 'Closer')?.group).toBe(savedGroup);
        }
    );
});

describe('AgentsPageStore agent export', () => {
    let downloads: string[];
    const originalCreateObjectURL = URL.createObjectURL;
    const originalRevokeObjectURL = URL.revokeObjectURL;

    beforeEach(() => {
        downloads = [];
        URL.createObjectURL = () => 'blob:agents';
        URL.revokeObjectURL = () => undefined;
        vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(function (this: HTMLAnchorElement) {
            downloads.push(this.download);
        });
    });

    afterEach(() => {
        URL.createObjectURL = originalCreateObjectURL;
        URL.revokeObjectURL = originalRevokeObjectURL;
        vi.restoreAllMocks();
    });

    /** The store over three agents, with the export endpoints and the toast spied on. */
    function exportStore() {
        const store = loadStore({ agents: [agent(1, 'Alpha', null), agent(2, 'Beta', null), agent(3, 'Gamma', null)] });
        const exported = of({ blob: new Blob(['{}']), excluded: [] });
        const api = Object.assign(TestBed.inject(AgentDefinitionsApiService), {
            exportAgent: vi.fn(() => exported),
            bulkExportAgents: vi.fn(() => exported),
        });
        const toast = Object.assign(TestBed.inject(ToastService), { info: vi.fn() });
        return { store, api, toast };
    }

    it('starts every export with nothing ticked', () => {
        const { store } = exportStore();
        store.toggleAgentSelection(1);

        store.startAgentExport();

        expect(store.agentExportMode()).toBe(true);
        expect(store.selectedAgentIds().size).toBe(0);
    });

    it('sends only the ticked agents that still exist, downloads one file and leaves export mode', () => {
        const { store, api } = exportStore();
        store.startAgentExport();
        store.toggleAgentSelection(1);
        store.toggleAgentSelection(3);
        store.toggleAgentSelection(99);

        store.confirmAgentExport();

        expect(api.bulkExportAgents).toHaveBeenCalledExactlyOnceWith([1, 3]);
        expect(downloads).toHaveLength(1);
        expect(downloads[0]).toMatch(/^agents_export_\d+\.json$/);
        expect(store.agentExportMode()).toBe(false);
        expect(store.selectedAgentIds().size).toBe(0);
    });

    it('asks for a ticked agent instead of exporting nothing, and stays in export mode', () => {
        const { store, api, toast } = exportStore();
        store.startAgentExport();

        store.confirmAgentExport();

        expect(api.bulkExportAgents).not.toHaveBeenCalled();
        expect(toast.info).toHaveBeenCalledExactlyOnceWith('Select at least one agent to export.');
        expect(store.agentExportMode()).toBe(true);
    });

    it('ticks every agent on Select all, and clears them on the next one', () => {
        const { store } = exportStore();
        store.startAgentExport();

        store.toggleSelectAllAgents();
        expect(store.allAgentsSelected()).toBe(true);
        expect([...store.selectedAgentIds()]).toEqual([1, 2, 3]);

        store.toggleSelectAllAgents();
        expect(store.selectedAgentIds().size).toBe(0);
    });

    it('exports one agent into a file named after it', () => {
        const { store, api } = exportStore();

        store.exportAgent(2);

        expect(api.exportAgent).toHaveBeenCalledExactlyOnceWith(2);
        expect(downloads).toEqual(['agent_Beta.json']);
    });

    it('exports nothing for an agent that is no longer in the list', () => {
        const { store, api } = exportStore();

        store.exportAgent(99);

        expect(api.exportAgent).not.toHaveBeenCalled();
        expect(downloads).toEqual([]);
    });
});

const AGENTS_URL = '/api/agent-definitions/';
const SURFACES_URL = '/api/surfaces/';
const GROUPS_URL = '/api/agent-labels/';

function agentOf(id: number, name: string): AgentDefinition {
    return {
        id,
        org: 1,
        name,
        group: null,
        description: '',
        instructions: '',
        instruction_list: [],
        llm_config: null,
        fallback_llm_config: null,
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
        backend
            .expectOne((request) => request.method === 'GET' && request.url === GROUPS_URL)
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

const REFUSAL_MESSAGE = "This agent runs with Files: Write, which you don't have. Contact an admin to change it.";
const REFUSAL_BODY = {
    status_code: 403,
    code: 'storage_grant_denied',
    message: REFUSAL_MESSAGE,
    missing_grants: ['write'],
};

describe('AgentsPageStore saves refused for missing Files permissions', () => {
    let store: AgentsPageStore;
    let httpMock: HttpTestingController;
    let toast: { error: ReturnType<typeof vi.fn>; success: ReturnType<typeof vi.fn>; info: ReturnType<typeof vi.fn> };

    beforeEach(() => {
        toast = { error: vi.fn(), success: vi.fn(), info: vi.fn() };
        TestBed.configureTestingModule({
            providers: [
                AgentsPageStore,
                provideHttpClient(),
                provideHttpClientTesting(),
                { provide: ConfigService, useValue: { apiUrl: '/api/' } },
                { provide: ToastService, useValue: toast },
                { provide: SurfaceCatalogsStore, useValue: { reloadLoadedCatalogs: vi.fn() } },
                { provide: PermissionsService, useValue: { can: () => true } },
            ],
        });
        store = TestBed.inject(AgentsPageStore);
        httpMock = TestBed.inject(HttpTestingController);
        store.agents.set([
            {
                id: 1,
                name: 'Writer',
                instruction_list: [{ name: 'Main', content: 'old' }],
                default_surfaces: [],
            } as unknown as AgentDefinition,
        ]);
        store.surfaces.set([{ id: 9, name: 'Docs', owner_agent: 1 } as unknown as Surface]);
    });

    afterEach(() => {
        vi.useRealTimers();
    });

    function refuse(url: string): void {
        httpMock.expectOne(url).flush(REFUSAL_BODY, { status: 403, statusText: 'Forbidden' });
    }

    it('toasts the server message when an instruction change is refused and restores the list', () => {
        store.updateInstructionList(1, [{ name: 'Main', content: 'new' }]);

        refuse('/api/agent-definitions/1/');

        expect(toast.error).toHaveBeenCalledExactlyOnceWith(REFUSAL_MESSAGE);
        expect(store.agents()[0].instruction_list).toEqual([{ name: 'Main', content: 'old' }]);
    });

    it('toasts the server message when a default-surfaces change is refused', () => {
        store.makeSurfaceShared(9);

        refuse('/api/agent-definitions/1/');

        expect(toast.error).toHaveBeenCalledExactlyOnceWith(REFUSAL_MESSAGE);
    });

    it('toasts the server message when a surface edit is refused', () => {
        vi.useFakeTimers();

        store.updateSurface(9, { instructions: 'changed' });
        vi.advanceTimersByTime(500);
        refuse('/api/surfaces/9/');

        expect(toast.error).toHaveBeenCalledExactlyOnceWith(REFUSAL_MESSAGE);
    });
});
