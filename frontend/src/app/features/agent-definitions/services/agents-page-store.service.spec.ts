import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { Provider, signal } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { ActionCode, ExportOptions, LabelColor, LabelDto, ResourceCode } from '@shared/models';
import { ExportOptionsDialogService } from '@shared/services';
import { EMPTY, Observable, of, Subject, throwError } from 'rxjs';

import { PermissionsService } from '../../../services/auth/permissions.service';
import { ProfileService } from '../../../services/auth/profile.service';
import { ConfigService } from '../../../services/config';
import { ToastService } from '../../../services/notifications';
import { storedZip } from '../../../shared/utils/read-export-envelope.testing';
import { AgentDefinition, CreateAgentDefinitionRequest } from '../models/agent-definition.model';
import { Surface } from '../models/surface.model';
import { SurfaceUsage } from '../models/surface-usage.model';
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

const NO_USAGE: SurfaceUsage = { agents: [], flows: [], hiddenAgentCount: 0, hiddenFlowCount: 0 };

/**
 * The real store over fake HTTP edges, loaded with the given rows. Like the API, PATCH and POST answer
 * with the saved row, and a group DELETE succeeds.
 */
function loadStore(rows: {
    agents: AgentDefinition[];
    surfaces?: Surface[];
    groups?: LabelDto[];
    getUsage?: (id: number) => Observable<SurfaceUsage>;
    /** False for a role with Surfaces READ but no Agents READ; the agents endpoint then answers 403. */
    canReadAgents?: boolean;
}): AgentsPageStore {
    const surfaces = rows.surfaces ?? [];
    TestBed.configureTestingModule({
        providers: [
            AgentsPageStore,
            {
                provide: AgentDefinitionsApiService,
                useValue: {
                    getAgentDefinitions: () =>
                        rows.canReadAgents === false ? throwError(() => new Error('forbidden')) : of(rows.agents),
                    partialUpdate: (id: number, body: Partial<AgentDefinition>) =>
                        of({ ...rows.agents.find((row) => row.id === id)!, ...body }),
                    create: (body: CreateAgentDefinitionRequest) => of(agent(99, body.name, body.group ?? null)),
                },
            },
            {
                provide: SurfacesApiService,
                useValue: {
                    getSurfaces: () => of(surfaces),
                    getUsage: rows.getUsage ?? (() => of(NO_USAGE)),
                    partialUpdate: (id: number, body: Partial<Surface>) =>
                        of({ ...surfaces.find((row) => row.id === id)!, ...body }),
                },
            },
            {
                provide: AgentGroupsApiService,
                useValue: { getLabels: () => of(rows.groups ?? []), deleteLabel: () => of(undefined) },
            },
            {
                provide: PermissionsService,
                useValue: {
                    can: (resource: ResourceCode, action: ActionCode) =>
                        !(
                            rows.canReadAgents === false &&
                            resource === ResourceCode.Agents &&
                            action === ActionCode.Read
                        ),
                },
            },
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

describe('AgentsPageStore section header group actions', () => {
    beforeEach(() => localStorage.clear());
    afterEach(() => localStorage.clear());

    function storeWithTwoGroups(): AgentsPageStore {
        return loadStore({
            agents: [agent(1, 'Lead qualifier', SALES)],
            surfaces: [surface(10, 'CRM access', SALES)],
            groups: [group(SALES, 'Sales'), group(SUPPORT, 'Support')],
        });
    }

    const collapsedState = (store: AgentsPageStore): Record<string, boolean[]> => ({
        agents: [SALES, SUPPORT].map((id) => store.isGroupCollapsed('agents', id)),
        surfaces: [SALES, SUPPORT].map((id) => store.isGroupCollapsed('surfaces', id)),
    });

    it('collapses every Shared Surfaces group and leaves the Agents groups alone', () => {
        const store = storeWithTwoGroups();

        store.setAllGroupsCollapsed('surfaces', true);

        expect(collapsedState(store)).toEqual({ agents: [false, false], surfaces: [true, true] });
    });

    it('expands every Shared Surfaces group and keeps the Agents groups collapsed', () => {
        const store = storeWithTwoGroups();
        store.setAllGroupsCollapsed('agents', true);
        store.setAllGroupsCollapsed('surfaces', true);

        store.setAllGroupsCollapsed('surfaces', false);

        expect(collapsedState(store)).toEqual({ agents: [true, true], surfaces: [false, false] });
    });

    it('opens the new group input in Shared Surfaces, expanding the section', () => {
        const store = storeWithTwoGroups();
        if (store.isSectionExpanded('surfaces')) store.toggleSection('surfaces');

        store.startNewGroup(null, 'surfaces');

        expect(store.newGroupDraft()).toEqual({ section: 'surfaces', assign: null });
        expect(store.isSectionExpanded('surfaces')).toBe(true);
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

/** The real store and its real API services, over a fake HTTP backend. */
function storeOverFakeBackend(providers: Provider[] = []): { store: AgentsPageStore; backend: HttpTestingController } {
    TestBed.configureTestingModule({
        providers: [
            provideHttpClient(),
            provideHttpClientTesting(),
            { provide: ConfigService, useValue: { apiUrl: '/api/' } as unknown as ConfigService },
            AgentsPageStore,
            { provide: PermissionsService, useValue: { can: () => true } },
            // Only reloaded after a failed surface save, which these tests never make.
            { provide: SurfaceCatalogsStore, useValue: {} },
            ...providers,
        ],
    });
    return { store: TestBed.inject(AgentsPageStore), backend: TestBed.inject(HttpTestingController) };
}

/** One page of a list endpoint, as the API answers it. */
const page = <T>(results: T[]) => ({ count: results.length, next: null, previous: null, results });

const isGet = (url: string) => (request: { method: string; url: string }) =>
    request.method === 'GET' && request.url === url;

/** Opens the page: the store loads agents, surfaces and groups; the backend answers with these rows. */
function loadPage(
    store: AgentsPageStore,
    backend: HttpTestingController,
    agents: AgentDefinition[],
    surfaces: Surface[] = []
): void {
    store.load();
    backend.expectOne(isGet(AGENTS_URL)).flush(page(agents));
    backend.expectOne(isGet(SURFACES_URL)).flush(page(surfaces));
    backend.expectOne(isGet(GROUPS_URL)).flush(page([]));
}

describe('AgentsPageStore: whether the agent shown is the one the latest draft was saved as', () => {
    let store: AgentsPageStore;
    let backend: HttpTestingController;

    beforeEach(() => ({ store, backend } = storeOverFakeBackend()));

    afterEach(() => backend.verify());

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
        loadPage(store, backend, [agentOf(3, 'Invoice Reader')]);
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

describe('AgentsPageStore duplicateAgent', () => {
    const COPY_URL = `${AGENTS_URL}3/copy/`;
    let store: AgentsPageStore;
    let backend: HttpTestingController;
    let toast: ToastService;

    beforeEach(() => {
        ({ store, backend } = storeOverFakeBackend());
        toast = TestBed.inject(ToastService);
        vi.spyOn(toast, 'error');
    });

    afterEach(() => backend.verify());

    it('adds the copy the server made and selects it', () => {
        loadPage(store, backend, [agentOf(3, 'Invoice Reader')]);

        store.duplicateAgent(3);
        backend
            .expectOne({ method: 'POST', url: COPY_URL })
            .flush(agentOf(8, 'Invoice Reader #2'), { status: 201, statusText: 'Created' });
        backend.expectOne(isGet(SURFACES_URL)).flush(page([]));

        expect(store.agents().map((row) => row.name)).toEqual(['Invoice Reader', 'Invoice Reader #2']);
        expect(store.selectedAgent()?.id).toBe(8);
        expect(store.saving()).toBe(false);
    });

    it('reloads surfaces even when the source owned none in the list, so a surface cloned for the copy shows', () => {
        loadPage(store, backend, [agentOf(3, 'Invoice Reader')], [surface(20, 'Web search', null)]);

        store.duplicateAgent(3);
        backend.expectOne({ method: 'POST', url: COPY_URL }).flush(agentOf(8, 'Invoice Reader #2'));
        const clone = surface(22, 'Reader inbox', null, 8);
        backend.expectOne(isGet(SURFACES_URL)).flush(page([surface(20, 'Web search', null), clone]));

        expect(store.surfaces().filter((row) => row.owner_agent === 8)).toEqual([clone]);
    });

    it('shows the server message and adds nothing when the copy fails', () => {
        loadPage(store, backend, [agentOf(3, 'Invoice Reader')]);
        const message = 'A copy with that name was just created; please retry.';

        store.duplicateAgent(3);
        backend
            .expectOne({ method: 'POST', url: COPY_URL })
            .flush({ message }, { status: 400, statusText: 'Bad Request' });

        expect(toast.error).toHaveBeenCalledExactlyOnceWith(message);
        expect(store.agents().map((row) => row.name)).toEqual(['Invoice Reader']);
        expect(store.saving()).toBe(false);
    });

    it('shows the server message and adds nothing when the agent owns surfaces the user may not create', () => {
        loadPage(store, backend, [agentOf(3, 'Invoice Reader')]);
        const message =
            'This agent owns surfaces, and copying it clones them, so it requires the Create permission on surfaces.';

        store.duplicateAgent(3);
        backend.expectOne({ method: 'POST', url: COPY_URL }).flush(
            {
                status_code: 403,
                code: 'agent_with_owned_surfaces_requires_surfaces_create_permission',
                message,
            },
            { status: 403, statusText: 'Forbidden' }
        );

        expect(toast.error).toHaveBeenCalledExactlyOnceWith(message);
        expect(store.agents().map((row) => row.name)).toEqual(['Invoice Reader']);
        expect(store.saving()).toBe(false);
    });

    it('adds nothing and stays quiet on an uncoded 403, which the forbidden interceptor already reported', () => {
        loadPage(store, backend, [agentOf(3, 'Invoice Reader')]);

        store.duplicateAgent(3);
        backend
            .expectOne({ method: 'POST', url: COPY_URL })
            .flush(
                { detail: 'You do not have permission to perform this action.' },
                { status: 403, statusText: 'Forbidden' }
            );

        expect(toast.error).not.toHaveBeenCalled();
        expect(store.agents().map((row) => row.name)).toEqual(['Invoice Reader']);
        expect(store.saving()).toBe(false);
    });
});

describe('AgentsPageStore agent export', () => {
    const EXPORT_JOBS_URL = `${AGENTS_URL}export-jobs/`;
    const JOB_URL = '/api/transfer-jobs/job-1/';
    const DOWNLOAD_URL = '/api/transfer-jobs/job-1/download/?ticket=t-1';
    let store: AgentsPageStore;
    let backend: HttpTestingController;
    let toast: ToastService;
    let downloads: string[];
    /** What the export options dialog answers; the user exports with knowledge unless a test says otherwise. */
    let exportOptionsAnswer: Observable<ExportOptions>;
    let exportOptionsAsked: { count: number; plural: string }[];

    beforeEach(() => {
        downloads = [];
        exportOptionsAnswer = of({ includeKnowledge: true });
        exportOptionsAsked = [];
        vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(function (this: HTMLAnchorElement) {
            downloads.push(this.href);
        });
        ({ store, backend } = storeOverFakeBackend([
            {
                provide: ExportOptionsDialogService,
                useValue: {
                    ask: (count: number, labels: { plural: string }) => {
                        exportOptionsAsked.push({ count, plural: labels.plural });
                        return exportOptionsAnswer;
                    },
                },
            },
        ]));
        toast = TestBed.inject(ToastService);
        vi.spyOn(toast, 'info');
        vi.spyOn(toast, 'error');
        vi.spyOn(toast, 'warning');
        loadPage(store, backend, [agentOf(1, 'Alpha'), agentOf(2, 'Beta'), agentOf(3, 'Gamma')]);
    });

    afterEach(() => {
        backend.verify();
        vi.restoreAllMocks();
    });

    /** The server accepts the export job; returns the ids it was asked to export. */
    function acceptExportJob(): unknown {
        const start = backend.expectOne({ method: 'POST', url: EXPORT_JOBS_URL });
        start.flush({ job_id: 'job-1' }, { status: 202, statusText: 'Accepted' });
        return start.request.body;
    }

    /** The job completes with `excluded` left out, and the server hands out a download ticket for its archive. */
    async function finishExportJob(excluded: { entity_type: string; entity_id: number; name: string | null }[] = []) {
        (await vi.waitFor(() => backend.expectOne(JOB_URL))).flush({
            id: 'job-1',
            kind: 'export',
            main_entity: 'AgentDefinition',
            status: 'completed',
            display_name: 'Beta',
            file_name: 'agent_Beta_2026-11-16.zip',
            result: { excluded },
            error: null,
            created_at: '2026-11-16T10:00:00Z',
            finished_at: '2026-11-16T10:01:00Z',
            expires_at: null,
        });
        backend
            .expectOne({ method: 'POST', url: '/api/transfer-jobs/job-1/download-ticket/' })
            .flush({ download_url: DOWNLOAD_URL });
    }

    it('starts every export with nothing ticked', () => {
        store.toggleAgentSelection(1);

        store.startAgentExport();

        expect(store.agentExportMode()).toBe(true);
        expect(store.selectedAgentIds().size).toBe(0);
    });

    it('ticks every agent on Select all, and clears them on the next one', () => {
        store.startAgentExport();

        store.toggleSelectAllAgents();
        expect(store.allAgentsSelected()).toBe(true);
        expect([...store.selectedAgentIds()]).toEqual([1, 2, 3]);

        store.toggleSelectAllAgents();
        expect(store.selectedAgentIds().size).toBe(0);
    });

    it('exports only the ticked agents that still exist in one job, leaves export mode and downloads the archive', async () => {
        store.startAgentExport();
        store.toggleAgentSelection(1);
        store.toggleAgentSelection(3);
        store.toggleAgentSelection(99);

        store.confirmAgentExport();

        expect(exportOptionsAsked).toEqual([{ count: 2, plural: 'agents' }]);
        expect(acceptExportJob()).toEqual({ ids: [1, 3], include_knowledge: true });
        expect(store.agentExportMode()).toBe(false);
        expect(store.selectedAgentIds().size).toBe(0);
        await finishExportJob();
        expect(downloads).toEqual([expect.stringContaining(DOWNLOAD_URL)]);
    });

    it('exports the agents without their knowledge when the user clears it', () => {
        exportOptionsAnswer = of({ includeKnowledge: false });

        store.exportAgent(2);

        const start = backend.expectOne({ method: 'POST', url: EXPORT_JOBS_URL });
        expect(start.request.body).toEqual({ ids: [2], include_knowledge: false });
        // Refused, so no job is polled after the test.
        start.flush(
            { status_code: 429, code: 'too_many_jobs', message: 'Busy.' },
            { status: 429, statusText: 'Too Many Requests' }
        );
    });

    it('exports nothing and keeps export mode and the ticks when the user cancels the export options', () => {
        exportOptionsAnswer = EMPTY;
        store.startAgentExport();
        store.toggleAgentSelection(2);

        store.confirmAgentExport();

        backend.expectNone(EXPORT_JOBS_URL);
        expect(store.agentExportMode()).toBe(true);
        expect([...store.selectedAgentIds()]).toEqual([2]);
    });

    it('asks for a ticked agent instead of exporting nothing, and stays in export mode', () => {
        store.startAgentExport();

        store.confirmAgentExport();

        expect(toast.info).toHaveBeenCalledExactlyOnceWith('Select at least one agent to export.');
        expect(store.agentExportMode()).toBe(true);
    });

    it('exports one agent as a job and warns about the tools left out of its archive', async () => {
        store.exportAgent(2);

        expect(acceptExportJob()).toEqual({ ids: [2], include_knowledge: true });
        await finishExportJob([{ entity_type: 'PythonCodeTool', entity_id: 5, name: 'Scraper' }]);

        expect(downloads).toEqual([expect.stringContaining(DOWNLOAD_URL)]);
        expect(vi.mocked(toast.warning).mock.calls[0][0]).toContain('1 Python tool (Scraper)');
    });

    it('exports nothing for an agent that is no longer in the list', () => {
        store.exportAgent(99);

        expect(exportOptionsAsked).toEqual([]);
        backend.expectNone(EXPORT_JOBS_URL);
    });

    it.each([
        {
            status: 404,
            statusText: 'Not Found',
            code: 'export_entities_not_found',
            message: 'Some agents were not found.',
        },
        { status: 403, statusText: 'Forbidden', code: 'permission_denied', message: 'You may not export agents.' },
    ])(
        "shows the server's reason when it refuses the export with $status, and keeps the ticks to try again",
        ({ status, statusText, code, message }) => {
            store.startAgentExport();
            store.toggleAgentSelection(2);

            store.confirmAgentExport();
            backend
                .expectOne({ method: 'POST', url: EXPORT_JOBS_URL })
                .flush({ status_code: status, code, message }, { status, statusText });
            backend.match((request) => request.method === 'GET');

            expect(toast.error).toHaveBeenCalledExactlyOnceWith(message);
            expect(store.agentExportMode()).toBe(true);
            expect([...store.selectedAgentIds()]).toEqual([2]);
            expect(downloads).toEqual([]);
        }
    );

    it('loads the agents again when an agent to export is gone', () => {
        store.exportAgent(2);
        backend
            .expectOne({ method: 'POST', url: EXPORT_JOBS_URL })
            .flush(
                { status_code: 404, code: 'export_entities_not_found', message: 'Not found.' },
                { status: 404, statusText: 'Not Found' }
            );

        backend.expectOne(isGet(AGENTS_URL)).flush(page([agentOf(1, 'Alpha'), agentOf(3, 'Gamma')]));
        backend.expectOne(isGet(SURFACES_URL)).flush(page([]));
        backend.expectOne(isGet(GROUPS_URL)).flush(page([]));

        expect(store.agents().map((row) => row.name)).toEqual(['Alpha', 'Gamma']);
    });
});

describe('AgentsPageStore agent import', () => {
    const INSPECT_URL = `${AGENTS_URL}import/inspect/`;
    const IMPORT_URL = `${AGENTS_URL}import/`;
    const IMPORT_JOBS_URL = `${AGENTS_URL}import-jobs/`;
    const JOB_URL = '/api/transfer-jobs/job-1/';
    const ENVELOPE = JSON.stringify({ main_entity: 'AgentDefinition', version: 1 });
    let store: AgentsPageStore;
    let backend: HttpTestingController;
    let toast: ToastService;

    beforeEach(() => {
        ({ store, backend } = storeOverFakeBackend([
            { provide: SurfaceCatalogsStore, useValue: { reloadLoadedCatalogs: () => undefined } },
        ]));
        toast = TestBed.inject(ToastService);
        vi.spyOn(toast, 'success');
        vi.spyOn(toast, 'error');
    });

    afterEach(() => {
        backend.verify();
        vi.restoreAllMocks();
    });

    /** Clicks Import and returns the file picker, which the test fills in. */
    function openPicker(): HTMLInputElement {
        const picker = document.createElement('input');
        vi.spyOn(picker, 'click').mockImplementation(() => undefined);
        const createElement = vi.spyOn(document, 'createElement').mockReturnValueOnce(picker);
        store.importAgents();
        createElement.mockRestore();
        return picker;
    }

    /** The user picks `file`; the server finds no code to review in it. */
    async function pickWithNothingToReview(file: File): Promise<void> {
        const picker = openPicker();
        Object.defineProperty(picker, 'files', { value: [file] });
        picker.dispatchEvent(new Event('change'));
        (await vi.waitFor(() => backend.expectOne({ method: 'POST', url: INSPECT_URL }))).flush({ review_items: [] });
    }

    function importJob(status: 'completed' | 'failed', error: { code: string; message: string } | null = null) {
        return {
            id: 'job-1',
            kind: 'import',
            main_entity: 'AgentDefinition',
            status,
            display_name: 'agents.zip',
            file_name: 'agents.zip',
            result: status === 'completed' ? { AgentDefinition: { total: 1 } } : null,
            error,
            created_at: '2026-11-17T10:00:00Z',
            finished_at: '2026-11-17T10:01:00Z',
            expires_at: null,
        };
    }

    /** The store reloads the agents, surfaces and groups. */
    function expectReload(): void {
        backend.expectOne(isGet(AGENTS_URL)).flush(page([]));
        backend.expectOne(isGet(SURFACES_URL)).flush(page([]));
        backend.expectOne(isGet(GROUPS_URL)).flush(page([]));
    }

    it('lets the user pick an agent export archive as well as a plain JSON export', () => {
        expect(openPicker().accept).toBe('.json,.zip');
    });

    it('imports an archive as a job, and reports success and reloads only once the job has finished', async () => {
        const archive = storedZip('agents.zip', { 'export.json': ENVELOPE });

        await pickWithNothingToReview(archive);

        const start = backend.expectOne((request) => request.method === 'POST' && request.url === IMPORT_JOBS_URL);
        expect(start.request.body).toBe(archive);
        expect(start.request.params.get('file_name')).toBe('agents.zip');
        start.flush({ job_id: 'job-1' }, { status: 202, statusText: 'Accepted' });
        backend.expectNone(IMPORT_URL);
        expect(toast.success).not.toHaveBeenCalled();

        (await vi.waitFor(() => backend.expectOne(JOB_URL))).flush(importJob('completed'));

        expect(toast.success).toHaveBeenCalledExactlyOnceWith('Agents imported successfully.');
        expectReload();
    });

    it("shows the server's reason when the import job fails, and reloads nothing", async () => {
        await pickWithNothingToReview(storedZip('agents.zip', { 'export.json': ENVELOPE }));
        backend
            .expectOne((request) => request.url === IMPORT_JOBS_URL)
            .flush({ job_id: 'job-1' }, { status: 202, statusText: 'Accepted' });

        (await vi.waitFor(() => backend.expectOne(JOB_URL))).flush(
            importJob('failed', { code: 'invalid_archive', message: 'The archive has no agents.' })
        );

        expect(toast.error).toHaveBeenCalledExactlyOnceWith('The archive has no agents.');
        expect(toast.success).not.toHaveBeenCalled();
    });

    it('imports a plain JSON export straight away, with no job', async () => {
        await pickWithNothingToReview(new File([ENVELOPE], 'agents.json', { type: 'application/json' }));

        backend.expectOne({ method: 'POST', url: IMPORT_URL }).flush({});
        backend.expectNone((request) => request.url === IMPORT_JOBS_URL);

        expect(toast.success).toHaveBeenCalledExactlyOnceWith('Agents imported successfully.');
        expectReload();
    });
});

describe('AgentsPageStore surface usage', () => {
    const flowUsage = (flowName: string): SurfaceUsage => ({
        ...NO_USAGE,
        flows: [{ flowId: 7, flowName, nodes: [] }],
    });

    /** Lets the resource's effect start its request and the (synchronous) fake answer land. */
    async function settle(): Promise<void> {
        TestBed.tick();
        await Promise.resolve();
        TestBed.tick();
    }

    it('loads nothing until a surface is selected, then loads that surface from the server', async () => {
        const getUsage = vi.fn((id: number) => of(flowUsage(`flow of ${id}`)));
        const store = loadStore({ agents: [], surfaces: [surface(10, 'CRM access', null)], getUsage });
        await settle();
        expect(getUsage).not.toHaveBeenCalled();

        store.selectSurface(10);
        await settle();

        expect(getUsage).toHaveBeenCalledExactlyOnceWith(10);
        expect(store.selectedSurfaceUsage.value()?.flows[0].flowName).toBe('flow of 10');
    });

    it('loads the usage of any surface for the dialog, again on each open, and lets go on close', async () => {
        const getUsage = vi.fn((id: number) => of(flowUsage(`flow of ${id}`)));
        const store = loadStore({
            agents: [],
            surfaces: [surface(10, 'CRM access', null), surface(11, 'Billing', null)],
            getUsage,
        });

        const usage = store.openSurfaceUsage(11);
        await settle();
        expect(getUsage).toHaveBeenCalledExactlyOnceWith(11);
        expect(usage.value()?.flows[0].flowName).toBe('flow of 11');

        store.openSurfaceUsage(11);
        await settle();
        expect(getUsage).toHaveBeenCalledTimes(2);

        store.closeSurfaceUsage();
        await settle();
        expect(usage.value()).toBeUndefined();
    });

    it('drops the answer of the previous surface when another is selected', async () => {
        const pending = new Subject<SurfaceUsage>();
        const getUsage = (id: number): Observable<SurfaceUsage> => (id === 10 ? pending : of(flowUsage('flow of 11')));
        const store = loadStore({
            agents: [],
            surfaces: [surface(10, 'CRM access', null), surface(11, 'Billing', null)],
            getUsage,
        });
        store.selectSurface(10);
        await settle();

        store.selectSurface(11);
        await settle();
        pending.next(flowUsage('stale flow of 10'));
        await settle();

        expect(store.selectedSurfaceUsage.value()?.flows[0].flowName).toBe('flow of 11');
    });

    it('loads again once an agent starts using the selected surface', async () => {
        const getUsage = vi.fn(() => of(NO_USAGE));
        const holder = agent(1, 'Researcher', null);
        const store = loadStore({ agents: [holder], surfaces: [surface(10, 'CRM access', null)], getUsage });
        store.selectSurface(10);
        await settle();
        expect(getUsage).toHaveBeenCalledTimes(1);

        store.agents.set([{ ...holder, default_surfaces: [{ surface: 10, place: 'chat' }] }]);
        await settle();

        expect(getUsage).toHaveBeenCalledTimes(2);
    });

    it('does not load again when an agent changes without touching the selected surface', async () => {
        const getUsage = vi.fn(() => of(NO_USAGE));
        const holder = agent(1, 'Researcher', null);
        const store = loadStore({ agents: [holder], surfaces: [surface(10, 'CRM access', null)], getUsage });
        store.selectSurface(10);
        await settle();

        store.agents.set([{ ...holder, name: 'Renamed' }]);
        await settle();

        expect(getUsage).toHaveBeenCalledTimes(1);
    });

    it('does not load again when only the order of the agents changes', async () => {
        const getUsage = vi.fn(() => of(NO_USAGE));
        const first = agent(1, 'Researcher', null, [10]);
        const second = agent(2, 'Writer', null, [10]);
        const store = loadStore({ agents: [first, second], surfaces: [surface(10, 'CRM access', null)], getUsage });
        store.selectSurface(10);
        await settle();
        expect(getUsage).toHaveBeenCalledTimes(1);

        store.agents.set([second, first]);
        await settle();

        expect(getUsage).toHaveBeenCalledTimes(1);
    });

    it('reports a failed load for the delete confirmation as null and tells the user', () => {
        const error = vi.fn();
        const store = loadStore({
            agents: [],
            getUsage: () => throwError(() => new Error('boom')),
        });
        TestBed.inject(ToastService).error = error;
        let result: SurfaceUsage | null | undefined;

        store.loadSurfaceUsage(10).subscribe((usage) => (result = usage));

        expect(result).toBeNull();
        expect(error).toHaveBeenCalledOnce();
    });
});

describe('AgentsPageStore for a role without Agents READ', () => {
    beforeEach(() => localStorage.clear());
    afterEach(() => localStorage.clear());

    it('loads the shared surfaces without asking for agents and reports no agents error', () => {
        const store = loadStore({
            agents: [],
            surfaces: [surface(10, 'Web search', null), surface(11, 'Owned', null, 1)],
            canReadAgents: false,
        });

        expect(store.agentsError()).toBeNull();
        expect(store.agents()).toEqual([]);
        expect(labels(store.surfacesTree())).toEqual(['Web search']);
    });

    it('shows only the Shared Surfaces section, open, even when the saved filter lists Agents', () => {
        localStorage.setItem('agents-explorer/visibleSections', JSON.stringify(['agents', 'surfaces']));
        const store = loadStore({ agents: [], canReadAgents: false });

        expect(store.isSectionVisible('agents')).toBe(false);
        expect(store.isSectionVisible('surfaces')).toBe(true);
        expect(store.isSectionExpanded('surfaces')).toBe(true);
        expect(store.isSectionExpanded('agents')).toBe(false);
    });

    it.each([[JSON.stringify(['agents'])], [JSON.stringify([])]])(
        'never leaves the explorer blank: saved filter %s still shows Shared Surfaces',
        (saved) => {
            localStorage.setItem('agents-explorer/visibleSections', saved);
            const store = loadStore({ agents: [], canReadAgents: false });

            expect([...store.visibleSections()]).toEqual(['surfaces']);
        }
    );

    it('keeps Shared Surfaces when the filter is saved with no sections', () => {
        const store = loadStore({ agents: [], canReadAgents: false });

        store.setVisibleSections(new Set());

        expect([...store.visibleSections()]).toEqual(['surfaces']);
    });

    it('keeps the Agents section for a role with Agents READ', () => {
        const store = loadStore({ agents: [agent(1, 'Alpha', null)] });

        expect(store.isSectionVisible('agents')).toBe(true);
        expect(store.isSectionExpanded('agents')).toBe(true);
    });
});
