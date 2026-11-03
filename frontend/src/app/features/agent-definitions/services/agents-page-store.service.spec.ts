import { signal } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { LabelColor, LabelDto } from '@shared/models';
import { of } from 'rxjs';

import { PermissionsService } from '../../../services/auth/permissions.service';
import { ProfileService } from '../../../services/auth/profile.service';
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
