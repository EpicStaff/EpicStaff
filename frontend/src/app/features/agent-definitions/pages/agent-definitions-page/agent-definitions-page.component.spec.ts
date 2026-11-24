import { CdkTrapFocus } from '@angular/cdk/a11y';
import { Dialog } from '@angular/cdk/dialog';
import { OverlayContainer, OverlayModule } from '@angular/cdk/overlay';
import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting, TestRequest } from '@angular/common/http/testing';
import { Component, CUSTOM_ELEMENTS_SCHEMA, forwardRef, input, signal, WritableSignal } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { ControlValueAccessor, NG_VALUE_ACCESSOR, ReactiveFormsModule } from '@angular/forms';
import { MatTooltip } from '@angular/material/tooltip';
import { By } from '@angular/platform-browser';
import { ActivatedRoute, convertToParamMap, Router } from '@angular/router';
import {
    AppSvgIconComponent,
    AuthorshipDetailsDialogService,
    ConfirmationDialogService,
    UnsavedChangesDialogService,
} from '@shared/components';
import { EnterBlurDirective, HasPermissionDirective } from '@shared/directives';
import { ActionCode, ResourceCode } from '@shared/models';
import { of, Subject } from 'rxjs';

import { tourAnchorSelector } from '../../../../core/guided-tour';
import { PermissionsService } from '../../../../services/auth/permissions.service';
import { ProfileService } from '../../../../services/auth/profile.service';
import { ConfigService } from '../../../../services/config';
import { ToastService } from '../../../../services/notifications';
import { CREATE_AGENT_TOUR_ANCHORS } from '../../../create-agent-tour/create-agent-tour-anchors';
import { StorageTreeFacade } from '../../../files/services/storage-tree-facade.service';
import { AgentDefinition } from '../../models/agent-definition.model';
import { Surface } from '../../models/surface.model';
import { AgentGroupsStorageService } from '../../services/agent-groups-storage.service';
import { AgentsPageStore } from '../../services/agents-page-store.service';
import { SurfaceCatalogsStore } from '../../services/surface-catalogs-store.service';
import { SurfacesApiService } from '../../services/surfaces-api.service';
import { AgentDefinitionsPageComponent } from './agent-definitions-page.component';
import { AgentDetailComponent } from './components/agent-detail/agent-detail.component';
import { DetailHeaderComponent } from './components/detail-header/detail-header.component';
import { AGENTS_SECTION_MENU_ACTION } from './components/explorer/explorer-menu.util';

const AGENT: AgentDefinition = {
    id: 3,
    org: 1,
    name: 'CV Processor',
    description: '',
    instructions: '',
    instruction_list: [],
    llm_config: null,
    fallback_llm_config: null,
    fcm_llm_config: null,
    agent_definition_realtime_config_id: null,
    has_realtime_definition: false,
    default_surfaces: [],
    group: null,
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
    created_at: '2026-03-12T13:28:23Z',
    created_by: { id: 1, display_name: 'Ivan Bohun', avatar_url: null },
    last_edited_by: { id: 2, display_name: 'Olena Petrenko', avatar_url: null },
    last_edited_at: '2026-03-13T09:00:00Z',
};

/** Just enough of the page store to render the agent editor with `AGENT` selected. */
function agentSelectedStore(): Partial<Record<keyof AgentsPageStore, unknown>> {
    return {
        load: () => undefined,
        selectAgent: vi.fn(),
        updateAgent: vi.fn(() => of({ saved: true })),
        saveNewAgent: vi.fn(() => of({ saved: true })),
        loading: signal(false),
        selectedNode: signal({ kind: 'agent', id: AGENT.id }),
        showSidebar: signal(false),
        isStorageSelected: signal(false),
        selectedAgentDoc: signal(null),
        selectedSurfaceView: signal(null),
        selectedAgent: signal(AGENT),
        selectedSurface: signal(null),
        selectedAgentFocus: signal(null),
        selectedAgentInstructionListError: signal(null),
        isDraftingAgent: signal(false),
        agentDraftId: signal(0),
        isDraftingSurface: signal(false),
        isSelectedAgentFromLatestDraft: signal(false),
        saving: signal(false),
        agents: signal([AGENT]),
        surfaces: signal([]),
        agentSaveErrorTick: signal(0),
        surfaceSaveError: signal(null),
        surfaceCreateErrorTick: signal(0),
        sharedSurfaceIdSet: signal(new Set<number>()),
        groups: signal([]),
    };
}

/** Every permission granted (`true`), none (`false`), or the answer per resource and action. */
type Grants = boolean | ((resource: ResourceCode, action: ActionCode) => boolean);

function render(
    grants: Grants,
    queryParams: Record<string, string> = {}
): {
    fixture: ComponentFixture<AgentDefinitionsPageComponent>;
    host: HTMLElement;
    overlay: HTMLElement;
} {
    const can = typeof grants === 'function' ? grants : () => grants;
    TestBed.configureTestingModule({
        providers: [
            {
                provide: PermissionsService,
                useValue: {
                    active: signal(null),
                    can,
                    canAny: (resource: ResourceCode, actions: ActionCode[]) =>
                        actions.some((action) => can(resource, action)),
                },
            },
            { provide: ActivatedRoute, useValue: { snapshot: { queryParamMap: convertToParamMap(queryParams) } } },
            {
                provide: Router,
                useValue: { navigate: () => Promise.resolve(true), lastSuccessfulNavigation: () => null },
            },
            { provide: UnsavedChangesDialogService, useValue: {} },
            { provide: ConfirmationDialogService, useValue: {} },
            // The breadcrumb group picker reads the org's groups.
            { provide: AgentGroupsStorageService, useValue: { labelTree: signal([]), loadLabels: () => of([]) } },
        ],
    });
    // Only the editor header is under test: the explorer and editor panes stay unrendered custom elements.
    TestBed.overrideComponent(AgentDefinitionsPageComponent, {
        set: {
            imports: [DetailHeaderComponent, AppSvgIconComponent, OverlayModule, CdkTrapFocus, HasPermissionDirective],
            providers: [
                { provide: AgentsPageStore, useValue: agentSelectedStore() },
                {
                    provide: StorageTreeFacade,
                    useValue: { init: () => undefined, selectedFile: signal(null), selectedItems: signal([]) },
                },
                { provide: SurfaceCatalogsStore, useValue: {} },
            ],
            schemas: [CUSTOM_ELEMENTS_SCHEMA],
        },
    });
    const fixture = TestBed.createComponent(AgentDefinitionsPageComponent);
    fixture.detectChanges();
    const overlay = TestBed.inject(OverlayContainer).getContainerElement();
    return { fixture, host: fixture.nativeElement as HTMLElement, overlay };
}

function moreButton(host: HTMLElement): HTMLButtonElement | null {
    return host.querySelector<HTMLButtonElement>('.detail-header__kebab');
}

/** The stubbed store's `saving` flag, which disables the header trigger while true. */
function savingSignal(fixture: ComponentFixture<AgentDefinitionsPageComponent>): WritableSignal<boolean> {
    return fixture.debugElement.injector.get(AgentsPageStore).saving as WritableSignal<boolean>;
}

// Focused first, as a real click or Enter leaves it: the menu's focus trap hands the focus back to whatever had it
// when the menu opened, and a test must not depend on what an earlier spec left focused.
function openMenu(fixture: ComponentFixture<AgentDefinitionsPageComponent>): void {
    moreButton(fixture.nativeElement)!.focus();
    moreButton(fixture.nativeElement)!.click();
    fixture.detectChanges();
}

function menuItemLabels(overlay: HTMLElement): string[] {
    return Array.from(overlay.querySelectorAll('.detail-header__menu-item')).map(
        (item) => item.textContent?.trim() ?? ''
    );
}

function viewDetailsItem(overlay: HTMLElement): HTMLButtonElement | null {
    return (
        Array.from(overlay.querySelectorAll<HTMLButtonElement>('.detail-header__menu-item')).find(
            (item) => item.textContent?.trim() === 'View Details'
        ) ?? null
    );
}

describe('AgentDefinitionsPageComponent ?agentId= deep link', () => {
    /** Renders the page from `queryParams` and lets its agent list finish loading, `loads` times. */
    function renderLoaded(queryParams: Record<string, string>, loads = 1): AgentsPageStore {
        const { fixture } = render(false, queryParams);
        const store = fixture.debugElement.injector.get(AgentsPageStore);
        const loading = store.loading as WritableSignal<boolean>;
        for (let load = 0; load < loads; load++) {
            loading.set(true);
            fixture.detectChanges();
            loading.set(false);
            fixture.detectChanges();
        }
        return store;
    }

    it('selects the agent once its list has loaded, for a viewer who can only read agents', () => {
        const store = renderLoaded({ agentId: String(AGENT.id) });

        expect(store.selectAgent).toHaveBeenCalledExactlyOnceWith(AGENT.id);
    });

    it('does not select it again when the list reloads', () => {
        const store = renderLoaded({ agentId: String(AGENT.id) }, 2);

        expect(store.selectAgent).toHaveBeenCalledExactlyOnceWith(AGENT.id);
    });

    it('ignores an agent id that is not in the list', () => {
        const store = renderLoaded({ agentId: '999' });

        expect(store.selectAgent).not.toHaveBeenCalled();
    });
});

describe('AgentDefinitionsPageComponent agent header menu "View Details"', () => {
    it('sits between Duplicate and Delete', () => {
        const { fixture, overlay } = render(true);

        openMenu(fixture);

        expect(menuItemLabels(overlay)).toEqual(['Duplicate', 'View Details', 'Delete']);
    });

    it('is offered to a user who can only read agents, as the only item', () => {
        const { fixture, host, overlay } = render(false);

        expect(moreButton(host)).not.toBeNull();
        openMenu(fixture);

        expect(menuItemLabels(overlay)).toEqual(['View Details']);
    });

    it('opens "Agent Details" for the agent, to close back to the trigger, and closes the menu', () => {
        const { fixture, host, overlay } = render(true);
        const open = vi
            .spyOn(TestBed.inject(AuthorshipDetailsDialogService), 'open')
            .mockReturnValue({} as ReturnType<AuthorshipDetailsDialogService['open']>);

        openMenu(fixture);
        viewDetailsItem(overlay)!.click();
        fixture.detectChanges();

        expect(open).toHaveBeenCalledWith('Agent Details', AGENT, moreButton(host));
        expect(viewDetailsItem(overlay)).toBeNull();
    });

    it('returns focus to the trigger once the details dialog closes, not to the destroyed menu item', () => {
        const { fixture, host, overlay } = render(true);
        const dialog = TestBed.inject(Dialog);
        const trigger = moreButton(host)!;

        openMenu(fixture);
        viewDetailsItem(overlay)!.focus();
        viewDetailsItem(overlay)!.click();
        fixture.detectChanges();
        expect(dialog.openDialogs).toHaveLength(1);

        dialog.openDialogs[0].close();
        fixture.detectChanges();

        expect(dialog.openDialogs).toHaveLength(0);
        expect(document.activeElement).toBe(trigger);
    });

    it('returns focus to a trigger that was disabled by a save when the dialog opened but is enabled on close', () => {
        const { fixture, host, overlay } = render(true);
        const dialog = TestBed.inject(Dialog);
        const trigger = moreButton(host)!;

        openMenu(fixture);
        savingSignal(fixture).set(true);
        fixture.detectChanges();
        expect(trigger.disabled).toBe(true);
        viewDetailsItem(overlay)!.focus();
        viewDetailsItem(overlay)!.click();
        fixture.detectChanges();

        savingSignal(fixture).set(false);
        fixture.detectChanges();
        dialog.openDialogs[0].close();
        fixture.detectChanges();

        expect(document.activeElement).toBe(trigger);
    });

    it('leaves focus on the body when the trigger is still disabled on close', () => {
        const { fixture, overlay } = render(true);
        const dialog = TestBed.inject(Dialog);

        openMenu(fixture);
        savingSignal(fixture).set(true);
        fixture.detectChanges();
        viewDetailsItem(overlay)!.focus();
        viewDetailsItem(overlay)!.click();
        fixture.detectChanges();

        dialog.openDialogs[0].close();
        fixture.detectChanges();

        expect(document.activeElement).toBe(document.body);
    });
});

describe('AgentDefinitionsPageComponent agent header menu "Duplicate"', () => {
    const OWNED_SURFACE = {
        id: 20,
        name: 'Reader inbox',
        group: null,
        owner_agent: AGENT.id,
    } as Partial<Surface> as Surface;

    /** Renders with the agent owning a surface, granting everything except, optionally, Surfaces:Create. */
    function renderOwningSurface(canCreateSurfaces: boolean): {
        fixture: ComponentFixture<AgentDefinitionsPageComponent>;
        overlay: HTMLElement;
    } {
        const { fixture, overlay } = render(
            (resource, action) =>
                canCreateSurfaces || !(resource === ResourceCode.Surfaces && action === ActionCode.Create)
        );
        const store = fixture.debugElement.injector.get(AgentsPageStore);
        (store.surfaces as WritableSignal<Surface[]>).set([OWNED_SURFACE]);
        fixture.detectChanges();
        return { fixture, overlay };
    }

    it('is hidden for an agent that owns a surface when the user cannot create surfaces, as the copy clones it', () => {
        const { fixture, overlay } = renderOwningSurface(false);

        openMenu(fixture);

        expect(menuItemLabels(overlay)).toEqual(['View Details', 'Delete']);
    });

    it('is offered for an agent that owns a surface when the user can create surfaces', () => {
        const { fixture, overlay } = renderOwningSurface(true);

        openMenu(fixture);

        expect(menuItemLabels(overlay)).toEqual(['Duplicate', 'View Details', 'Delete']);
    });
});

describe('AgentDefinitionsPageComponent Create Agent tour anchors', () => {
    function markedWith(host: HTMLElement, anchor: string): Element | null {
        return host.querySelector(tourAnchorSelector(anchor));
    }

    it('marks the Add Agent button', () => {
        const { host } = render(true);

        expect(markedWith(host, CREATE_AGENT_TOUR_ANCHORS.addAgent)?.textContent?.trim()).toBe('Add Agent');
    });

    it('marks the agent editor as created only while it shows the agent the latest draft was saved as', () => {
        const { fixture, host } = render(true);
        expect(markedWith(host, CREATE_AGENT_TOUR_ANCHORS.createdAgent)).toBeNull();

        const store = fixture.debugElement.injector.get(AgentsPageStore);
        (store.isSelectedAgentFromLatestDraft as WritableSignal<boolean>).set(true);
        fixture.detectChanges();

        expect(markedWith(host, CREATE_AGENT_TOUR_ANCHORS.createdAgent)?.tagName).toBe('APP-AGENT-DETAIL');
    });
});

describe('AgentDefinitionsPageComponent explorer row menu "View Details"', () => {
    const OTHER_AGENT: AgentDefinition = {
        ...AGENT,
        id: 7,
        name: 'Invoice Reader',
        created_by: { id: 4, display_name: 'Taras Melnyk', avatar_url: null },
    };

    function spyOnDetailsDialog() {
        return vi
            .spyOn(TestBed.inject(AuthorshipDetailsDialogService), 'open')
            .mockReturnValue({} as ReturnType<AuthorshipDetailsDialogService['open']>);
    }

    it("opens 'Agent Details' for the row's agent, not the selected one, to close back to the row's ⋮", () => {
        const { fixture } = render(true);
        const store = fixture.debugElement.injector.get(AgentsPageStore);
        (store.agents as WritableSignal<AgentDefinition[]>).set([AGENT, OTHER_AGENT]);
        const open = spyOnDetailsDialog();
        const trigger = document.createElement('button');

        fixture.componentInstance.onExplorerTreeMenu({
            node: { kind: 'agent', agentId: OTHER_AGENT.id, label: OTHER_AGENT.name, children: [] },
            action: 'view-details',
            trigger,
        });

        expect(open).toHaveBeenCalledExactlyOnceWith('Agent Details', OTHER_AGENT, trigger);
    });

    it('opens without the unsaved-changes prompt, since it neither navigates nor discards edits', () => {
        const { fixture } = render(true);
        const open = spyOnDetailsDialog();
        fixture.componentInstance.onDirtyChange(true);

        fixture.componentInstance.onExplorerTreeMenu({
            node: { kind: 'agent', agentId: AGENT.id, label: AGENT.name, children: [] },
            action: 'view-details',
            trigger: document.createElement('button'),
        });

        // The stubbed UnsavedChangesDialogService has no confirm: prompting would throw.
        expect(open).toHaveBeenCalledOnce();
    });

    it("opens nothing when the row's agent is no longer in the store", () => {
        const { fixture } = render(true);
        const store = fixture.debugElement.injector.get(AgentsPageStore);
        (store.agents as WritableSignal<AgentDefinition[]>).set([AGENT]);
        const open = spyOnDetailsDialog();

        fixture.componentInstance.onExplorerTreeMenu({
            node: { kind: 'agent', agentId: OTHER_AGENT.id, label: OTHER_AGENT.name, children: [] },
            action: 'view-details',
            trigger: document.createElement('button'),
        });

        expect(open).not.toHaveBeenCalled();
    });
});

describe('AgentDefinitionsPageComponent Agents section menu', () => {
    function stubImportExport(fixture: ComponentFixture<AgentDefinitionsPageComponent>) {
        const actions = { importAgents: vi.fn(), startAgentExport: vi.fn() };
        Object.assign(fixture.debugElement.injector.get(AgentsPageStore), actions);
        return actions;
    }

    function chooseSectionItem(fixture: ComponentFixture<AgentDefinitionsPageComponent>, action: string): void {
        fixture.componentInstance.onExplorerTreeMenu({
            node: { kind: 'section-header', section: 'agents' },
            action,
            trigger: document.createElement('button'),
        });
    }

    it('imports agents on Import', () => {
        const { fixture } = render(true);
        const { importAgents, startAgentExport } = stubImportExport(fixture);

        chooseSectionItem(fixture, AGENTS_SECTION_MENU_ACTION.import);

        expect(importAgents).toHaveBeenCalledOnce();
        expect(startAgentExport).not.toHaveBeenCalled();
    });

    it('starts picking the agents to export on Export…', () => {
        const { fixture } = render(true);
        const { importAgents, startAgentExport } = stubImportExport(fixture);

        chooseSectionItem(fixture, AGENTS_SECTION_MENU_ACTION.export);

        expect(startAgentExport).toHaveBeenCalledOnce();
        expect(importAgents).not.toHaveBeenCalled();
    });
});

describe('AgentDefinitionsPageComponent agent row menu "Export"', () => {
    it('exports that agent', () => {
        const { fixture } = render(true);
        const exportAgent = vi.fn();
        Object.assign(fixture.debugElement.injector.get(AgentsPageStore), { exportAgent });

        fixture.componentInstance.onExplorerTreeMenu({
            node: { kind: 'agent', agentId: 3, label: 'CV Processor', children: [] },
            action: 'export',
            trigger: document.createElement('button'),
        });

        expect(exportAgent).toHaveBeenCalledExactlyOnceWith(3);
    });
});

describe('AgentDefinitionsPageComponent deleting a surface', () => {
    const SHARED_SURFACE = {
        id: 30,
        name: 'CRM access',
        group: null,
        owner_agent: null,
        python_tools: [],
        mcp_tools: [],
        storage_items: [],
        knowledge: [],
    } as Partial<Surface> as Surface;

    function renderDeleting(loadSurfaceUsage: () => unknown): {
        fixture: ComponentFixture<AgentDefinitionsPageComponent>;
        confirm: ReturnType<typeof vi.fn>;
        deleteSurface: ReturnType<typeof vi.fn>;
    } {
        const { fixture } = render(true);
        const confirm = vi.fn(() => of(true));
        const deleteSurface = vi.fn();
        TestBed.inject(ConfirmationDialogService).confirm = confirm as unknown as ConfirmationDialogService['confirm'];
        const store = fixture.debugElement.injector.get(AgentsPageStore);
        (store.surfaces as WritableSignal<Surface[]>).set([SHARED_SURFACE]);
        Object.assign(store, { loadSurfaceUsage, deleteSurface });
        return { fixture, confirm, deleteSurface };
    }

    it('warns with the counts fetched for that surface, hidden ones included', () => {
        const { fixture, confirm, deleteSurface } = renderDeleting(() =>
            of({
                agents: [
                    { agentId: 1, agentName: 'Researcher', placeLabel: 'Chat' },
                    { agentId: 1, agentName: 'Researcher', placeLabel: 'Flow' },
                ],
                flows: [{ flowId: 7, flowName: 'My flow', nodes: [] }],
                hiddenAgentCount: 2,
                hiddenFlowCount: 1,
            })
        );

        fixture.componentInstance.onDeleteSurface(SHARED_SURFACE.id);

        expect(confirm.mock.calls[0][0].caution).toContain('3 agents and 2 flows');
        expect(deleteSurface).toHaveBeenCalledExactlyOnceWith(SHARED_SURFACE.id);
    });

    it('asks nothing and deletes nothing when the usage could not be loaded', () => {
        const { fixture, confirm, deleteSurface } = renderDeleting(() => of(null));

        fixture.componentInstance.onDeleteSurface(SHARED_SURFACE.id);

        expect(confirm).not.toHaveBeenCalled();
        expect(deleteSurface).not.toHaveBeenCalled();
    });

    it('ignores a repeat click while the usage is still being fetched', () => {
        const pending = new Subject<null>();
        const loadSurfaceUsage = vi.fn(() => pending);
        const { fixture } = renderDeleting(loadSurfaceUsage);

        fixture.componentInstance.onDeleteSurface(SHARED_SURFACE.id);
        fixture.componentInstance.onDeleteSurface(SHARED_SURFACE.id);

        expect(loadSurfaceUsage).toHaveBeenCalledTimes(1);
    });
});

describe('AgentDefinitionsPageComponent usage opened from a surface card', () => {
    it('shows the usage of that surface and lets the store go when the dialog closes', () => {
        const { fixture } = render(true);
        const usage = signal(undefined);
        const openSurfaceUsage = vi.fn(() => usage);
        const closeSurfaceUsage = vi.fn();
        Object.assign(fixture.debugElement.injector.get(AgentsPageStore), { openSurfaceUsage, closeSurfaceUsage });
        const closed = new Subject<number | undefined>();
        const open = vi
            .spyOn(TestBed.inject(Dialog), 'open')
            .mockReturnValue({ closed } as unknown as ReturnType<Dialog['open']>);

        fixture.componentInstance.onOpenSurfaceUsage(42);

        expect(openSurfaceUsage).toHaveBeenCalledExactlyOnceWith(42);
        expect(open.mock.calls[0][1]?.data).toEqual({ usage });
        expect(closeSurfaceUsage).not.toHaveBeenCalled();

        closed.next(undefined);

        expect(closeSurfaceUsage).toHaveBeenCalledTimes(1);
    });
});

describe('AgentDefinitionsPageComponent saving the agent', () => {
    const payload = {
        id: AGENT.id,
        name: AGENT.name,
        description: '',
        llm_config: 1,
        fallback_llm_config: 2,
        fcm_llm_config: null,
    };

    it('sends the fallback LLM with an update', () => {
        const { fixture } = render(true);
        const store = fixture.debugElement.injector.get(AgentsPageStore);

        fixture.componentInstance.onSaveAgent(payload);

        expect(store.updateAgent).toHaveBeenCalledWith(
            AGENT.id,
            expect.objectContaining({ llm_config: 1, fallback_llm_config: 2 })
        );
    });

    it('sends the fallback LLM when creating the agent', () => {
        const { fixture } = render(true);
        const store = fixture.debugElement.injector.get(AgentsPageStore);

        fixture.componentInstance.onSaveAgent({ ...payload, id: null });

        expect(store.saveNewAgent).toHaveBeenCalledWith(
            expect.objectContaining({ llm_config: 1, fallback_llm_config: 2 }),
            false
        );
    });
});

/** Stands in for the LLM model selector, which loads every LLM configuration of the organization. */
@Component({
    selector: 'app-llm-model-selector',
    template: '',
    providers: [
        { provide: NG_VALUE_ACCESSOR, useExisting: forwardRef(() => LlmModelSelectorStubComponent), multi: true },
    ],
})
class LlmModelSelectorStubComponent implements ControlValueAccessor {
    readonly excludedConfigId = input<number | null>(null);
    readonly readonly = input(false);

    private onChange: (configId: number | null) => void = () => undefined;

    /** What picking a model in the real selector does to the form. */
    pick(configId: number): void {
        this.onChange(configId);
    }

    writeValue(): void {}

    registerOnChange(onChange: (configId: number | null) => void): void {
        this.onChange = onChange;
    }

    registerOnTouched(): void {}
}

describe('AgentDefinitionsPageComponent leaving unsaved agent edits', () => {
    type PageFixture = ComponentFixture<AgentDefinitionsPageComponent>;

    const AGENTS_URL = '/api/agent-definitions/';
    const OTHER_AGENT: AgentDefinition = {
        ...AGENT,
        id: 7,
        name: 'Invoice Reader',
        instruction_list: [{ name: 'Matching', content: 'Match invoices to orders.' }],
    };
    const OTHER_AGENT_SURFACE = {
        id: 20,
        name: 'Invoices inbox',
        group: null,
        owner_agent: OTHER_AGENT.id,
    } as Partial<Surface> as Surface;
    const SHARED_SURFACE = {
        id: 21,
        name: 'CRM access',
        group: null,
        owner_agent: null,
    } as Partial<Surface> as Surface;
    /** `AGENT` as the server holds it, with an instruction to open. */
    const AGENT_ON_SERVER: AgentDefinition = {
        ...AGENT,
        instruction_list: [{ name: 'Screening', content: 'Screen incoming CVs.' }],
    };

    // jsdom has no Element.scrollTo, which opening an agent calls to scroll its editor up.
    beforeEach(() => {
        Element.prototype.scrollTo = () => undefined;
    });
    afterEach(() => {
        Reflect.deleteProperty(Element.prototype, 'scrollTo');
    });

    /**
     * The page with the real agent editor, on a draft (`drafting`) or on `AGENT`, with "About this Agent" typed and not
     * saved yet. `realStore` runs the real page store over the agents API, with `AGENT` and `OTHER_AGENT` on the server.
     */
    function renderEdited(
        drafting: boolean,
        realStore = false
    ): { fixture: PageFixture; store: AgentsPageStore; overlay: HTMLElement } {
        const stubStore = {
            ...agentSelectedStore(),
            selectedAgent: signal(drafting ? null : AGENT),
            isDraftingAgent: signal(drafting),
            beginCreateAgent: vi.fn(),
        };
        TestBed.configureTestingModule({
            providers: [
                provideHttpClient(),
                provideHttpClientTesting(),
                {
                    provide: PermissionsService,
                    useValue: { active: signal(null), can: () => true, canAny: () => true },
                },
                { provide: ActivatedRoute, useValue: { snapshot: { queryParamMap: convertToParamMap({}) } } },
                {
                    provide: Router,
                    useValue: { navigate: () => Promise.resolve(true), lastSuccessfulNavigation: () => null },
                },
                { provide: ConfirmationDialogService, useValue: {} },
                {
                    provide: AgentGroupsStorageService,
                    useValue: { labels: signal([]), labelTree: signal([]), loadLabels: () => of([]) },
                },
                { provide: ToastService, useValue: { info: vi.fn(), success: vi.fn(), error: vi.fn() } },
                { provide: ConfigService, useValue: { apiUrl: '/api/' } },
                {
                    provide: SurfacesApiService,
                    useValue: {
                        getSurfaces: () => of([OTHER_AGENT_SURFACE, SHARED_SURFACE]),
                        getUsage: () => of({ agents: [], flows: [], hiddenAgentCount: 0, hiddenFlowCount: 0 }),
                    },
                },
                { provide: ProfileService, useValue: { currentUserSignal: signal({ id: 7 }) } },
            ],
        });
        TestBed.overrideComponent(AgentDefinitionsPageComponent, {
            set: {
                imports: [
                    AgentDetailComponent,
                    DetailHeaderComponent,
                    AppSvgIconComponent,
                    OverlayModule,
                    CdkTrapFocus,
                    HasPermissionDirective,
                    MatTooltip,
                ],
                providers: [
                    realStore ? AgentsPageStore : { provide: AgentsPageStore, useValue: stubStore },
                    {
                        provide: StorageTreeFacade,
                        useValue: { init: () => undefined, selectedFile: signal(null), selectedItems: signal([]) },
                    },
                    { provide: SurfaceCatalogsStore, useValue: {} },
                ],
                schemas: [CUSTOM_ELEMENTS_SCHEMA],
            },
        });
        // The name form is under test; the instructions list and the Surfaces panel stay unrendered custom elements.
        TestBed.overrideComponent(AgentDetailComponent, {
            set: {
                imports: [
                    ReactiveFormsModule,
                    EnterBlurDirective,
                    HasPermissionDirective,
                    LlmModelSelectorStubComponent,
                ],
                schemas: [CUSTOM_ELEMENTS_SCHEMA],
            },
        });
        const fixture = TestBed.createComponent(AgentDefinitionsPageComponent);
        fixture.detectChanges();
        if (realStore) {
            TestBed.inject(HttpTestingController)
                .expectOne((request) => request.method === 'GET' && request.url === AGENTS_URL)
                .flush({ count: 2, next: null, previous: null, results: [AGENT_ON_SERVER, OTHER_AGENT] });
            const store = fixture.debugElement.injector.get(AgentsPageStore);
            if (drafting) store.beginCreateAgent();
            else store.selectAgent(AGENT.id);
            fixture.detectChanges();
        }
        // Typing in "About this Agent" takes the focus off the name field a draft opens on.
        const description = descriptionInput(fixture);
        description.focus();
        description.value = 'Reads CVs';
        description.dispatchEvent(new Event('input'));
        fixture.detectChanges();
        return {
            fixture,
            store: fixture.debugElement.injector.get(AgentsPageStore),
            overlay: TestBed.inject(OverlayContainer).getContainerElement(),
        };
    }

    function host(fixture: PageFixture): HTMLElement {
        return fixture.nativeElement as HTMLElement;
    }

    function nameInput(fixture: PageFixture): HTMLInputElement {
        return host(fixture).querySelector<HTMLInputElement>('input[aria-label="Agent Name"]')!;
    }

    function descriptionInput(fixture: PageFixture): HTMLTextAreaElement {
        return host(fixture).querySelector<HTMLTextAreaElement>('textarea[aria-label="About this Agent"]')!;
    }

    function type(fixture: PageFixture, field: HTMLInputElement | HTMLTextAreaElement, text: string): void {
        field.value = text;
        field.dispatchEvent(new Event('input'));
        fixture.detectChanges();
    }

    function nameError(fixture: PageFixture): string | null {
        return host(fixture).querySelector('.field__error')?.textContent?.trim() ?? null;
    }

    function dialogText(overlay: HTMLElement): { title: string; message: string; buttons: string[] } {
        return {
            title: overlay.querySelector('.dialog-title')?.textContent?.trim() ?? '',
            message: overlay.querySelector('.dialog-message')?.textContent?.trim() ?? '',
            buttons: Array.from(overlay.querySelectorAll('.dialog-actions button')).map(
                (button) => button.textContent?.trim() ?? ''
            ),
        };
    }

    async function choose(fixture: PageFixture, overlay: HTMLElement, label: string): Promise<void> {
        const button = Array.from(overlay.querySelectorAll<HTMLButtonElement>('.dialog-actions button')).find(
            (candidate) => candidate.textContent?.trim() === label
        );
        button!.click();
        await fixture.whenStable();
        fixture.detectChanges();
    }

    /** Leaving the route (`canDeactivate`) or starting another agent (`guardUnsaved`); `left()` says whether it went. */
    const LEAVE_BY = [
        { way: 'leaving the route', start: (fixture: PageFixture) => ({ left: leaveRoute(fixture) }) },
        {
            way: 'starting another agent',
            start: (fixture: PageFixture) => {
                fixture.componentInstance.onAddAgent();
                const beginCreateAgent = vi.mocked(fixture.debugElement.injector.get(AgentsPageStore).beginCreateAgent);
                return { left: (): boolean | undefined => beginCreateAgent.mock.calls.length > 0 };
            },
        },
    ];

    it.each(LEAVE_BY)('asks to discard a draft without offering Save, on $way', async ({ start }) => {
        const { fixture, overlay } = renderEdited(true);

        start(fixture);
        await fixture.whenStable();

        expect(dialogText(overlay)).toEqual({
            title: 'Agent not created',
            message: "This agent hasn't been created yet. Fix the name to save it, or discard it.",
            buttons: ['Discard & Leave', 'Keep Editing'],
        });
    });

    it.each(LEAVE_BY)('stays on Keep Editing and points at the empty name, on $way', async ({ start }) => {
        const { fixture, overlay } = renderEdited(true);
        const { left } = start(fixture);
        await fixture.whenStable();

        await choose(fixture, overlay, 'Keep Editing');

        expect(left()).toBe(false);
        expect(document.activeElement).toBe(nameInput(fixture));
        expect(nameError(fixture)).toBe('Agent name is required');
    });

    it.each(LEAVE_BY)('goes on Discard & Leave, on $way', async ({ start }) => {
        const { fixture, overlay } = renderEdited(true);
        const { left } = start(fixture);
        await fixture.whenStable();

        await choose(fixture, overlay, 'Discard & Leave');

        expect(left()).toBe(true);
    });

    it('drops the name error once a name is typed', async () => {
        const { fixture, overlay } = renderEdited(true);
        fixture.componentInstance.onAddAgent();
        await fixture.whenStable();
        await choose(fixture, overlay, 'Keep Editing');

        nameInput(fixture).value = 'CV Processor';
        nameInput(fixture).dispatchEvent(new Event('input'));
        fixture.detectChanges();

        expect(nameError(fixture)).toBeNull();
    });

    /** Leaving the route as Alt+← does, the focused field keeping the focus; the result is the guard's answer, if any yet. */
    function leaveRoute(fixture: PageFixture): () => boolean | undefined {
        let went: boolean | undefined;
        const answer = fixture.componentInstance.canDeactivate();
        if (typeof answer === 'boolean') went = answer;
        else answer.subscribe((leave) => (went = leave));
        return () => went;
    }

    /** A mouse click on an explorer row: pressing the button takes the focus off the field before the click lands. */
    function clickAgent(fixture: PageFixture, agent: AgentDefinition): void {
        (document.activeElement as HTMLElement | null)?.blur();
        fixture.componentInstance.onSelectNode({ kind: 'agent', agentId: agent.id, label: agent.name, children: [] });
    }

    /** Whether the agent editor is open on `agent`. */
    function shows(fixture: PageFixture, agent: AgentDefinition): boolean {
        fixture.detectChanges();
        return host(fixture).querySelector<HTMLInputElement>('input[aria-label="Agent Name"]')?.value === agent.name;
    }

    /** Leaving with the field focused, which leaves the save to the page, or by a click, which sends it first. */
    const LEAVE_FOR_ANOTHER_PLACE = [
        { way: 'leaving the route', start: (fixture: PageFixture) => ({ left: leaveRoute(fixture) }) },
        {
            way: 'clicking another agent',
            start: (fixture: PageFixture) => {
                clickAgent(fixture, OTHER_AGENT);
                return { left: () => shows(fixture, OTHER_AGENT) };
            },
        },
    ];

    const DRAFT_NAME = 'Cover Letter Writer';

    /** A draft named `DRAFT_NAME`, its name field still focused: the blur that would create it has not happened. */
    function renderNamedDraft(): ReturnType<typeof renderEdited> {
        const rendered = renderEdited(true, true);
        nameInput(rendered.fixture).focus();
        type(rendered.fixture, nameInput(rendered.fixture), DRAFT_NAME);
        return rendered;
    }

    async function settle(fixture: PageFixture): Promise<void> {
        fixture.detectChanges();
        await fixture.whenStable();
        fixture.detectChanges();
    }

    function expectAgentRequest(method: 'PATCH' | 'POST', url: string): TestRequest {
        return TestBed.inject(HttpTestingController).expectOne({ method, url });
    }

    const SAVE_FAILED = { status: 400, statusText: 'Bad Request' };

    it.each(LEAVE_FOR_ANOTHER_PLACE)(
        "saves a saved agent's pending edit without asking, and goes once it is saved, on $way",
        async ({ start }) => {
            const { fixture, overlay } = renderEdited(false, true);

            const { left } = start(fixture);
            const save = expectAgentRequest('PATCH', `${AGENTS_URL}${AGENT.id}/`);
            await settle(fixture);

            expect(save.request.body).toMatchObject({ name: AGENT.name, description: 'Reads CVs' });
            expect(dialogText(overlay).title).toBe('');
            expect(left()).not.toBe(true);

            save.flush({ ...AGENT, description: 'Reads CVs' });
            await settle(fixture);

            expect(left()).toBe(true);
        }
    );

    /** The agent's edit is sent on the leave and the server rejects it: the user is asked, with its reason. */
    async function leaveAndFailToSave(start: (typeof LEAVE_FOR_ANOTHER_PLACE)[number]['start']) {
        const rendered = renderEdited(false, true);
        const { left } = start(rendered.fixture);
        expectAgentRequest('PATCH', `${AGENTS_URL}${AGENT.id}/`).flush({ detail: 'Name is taken' }, SAVE_FAILED);
        await settle(rendered.fixture);
        return { ...rendered, left };
    }

    it.each(LEAVE_FOR_ANOTHER_PLACE)(
        'asks what to do when the edit fails to save, sending nothing behind the dialog, on $way',
        async ({ start }) => {
            const { overlay } = await leaveAndFailToSave(start);

            expect(dialogText(overlay)).toEqual({
                title: "Couldn't save your changes",
                message: 'Name is taken',
                buttons: ['Discard & Leave', 'Keep Editing'],
            });
            TestBed.inject(HttpTestingController).expectNone({ method: 'PATCH', url: `${AGENTS_URL}${AGENT.id}/` });
        }
    );

    it.each(LEAVE_FOR_ANOTHER_PLACE)(
        'stays with the edit kept on Keep Editing, and saves it on the next leave, on $way',
        async ({ start }) => {
            const { fixture, overlay, left } = await leaveAndFailToSave(start);

            await choose(fixture, overlay, 'Keep Editing');

            expect(left()).toBe(false);
            expect(descriptionInput(fixture).value).toBe('Reads CVs');

            const routeWent = leaveRoute(fixture);
            const retry = expectAgentRequest('PATCH', `${AGENTS_URL}${AGENT.id}/`);
            expect(retry.request.body).toMatchObject({ description: 'Reads CVs' });
            retry.flush({ ...AGENT, description: 'Reads CVs' });
            await settle(fixture);
            expect(routeWent()).toBe(true);
        }
    );

    it.each(LEAVE_FOR_ANOTHER_PLACE)(
        'drops the edit and goes on Discard & Leave, sending nothing more, on $way',
        async ({ start }) => {
            const { fixture, overlay, left } = await leaveAndFailToSave(start);

            await choose(fixture, overlay, 'Discard & Leave');

            expect(left()).toBe(true);
            TestBed.inject(HttpTestingController).expectNone({ method: 'PATCH', url: `${AGENTS_URL}${AGENT.id}/` });
        }
    );

    it('puts back what the server holds on Discard & Leave', async () => {
        const { fixture, overlay } = await leaveAndFailToSave(LEAVE_FOR_ANOTHER_PLACE[0].start);

        await choose(fixture, overlay, 'Discard & Leave');

        expect(descriptionInput(fixture).value).toBe(AGENT.description);
        expect(fixture.componentInstance.canDeactivate()).toBe(true);
    });

    it('keeps an edit whose save on blur failed, without asking, and saves it when the user leaves', async () => {
        const { fixture, overlay } = renderEdited(false, true);
        descriptionInput(fixture).blur();
        expectAgentRequest('PATCH', `${AGENTS_URL}${AGENT.id}/`).flush({ detail: 'Name is taken' }, SAVE_FAILED);
        await settle(fixture);

        expect(dialogText(overlay).title).toBe('');
        expect(descriptionInput(fixture).value).toBe('Reads CVs');

        clickAgent(fixture, OTHER_AGENT);
        const retry = expectAgentRequest('PATCH', `${AGENTS_URL}${AGENT.id}/`);
        expect(retry.request.body).toMatchObject({ description: 'Reads CVs' });
        retry.flush({ ...AGENT, description: 'Reads CVs' });
        await settle(fixture);

        expect(shows(fixture, OTHER_AGENT)).toBe(true);
    });

    /** Links that open an agent from a view other than the editor; `open` reaches the view, `follow` takes the link. */
    const AGENT_LINKS = [
        {
            link: 'the agent crumb above one of its surfaces',
            open: (store: AgentsPageStore) => store.selectSurface(OTHER_AGENT_SURFACE.id, OTHER_AGENT.id),
            follow: (fixture: PageFixture) =>
                Array.from(host(fixture).querySelectorAll<HTMLButtonElement>('.crumbs__item--link'))
                    .find((crumb) => crumb.textContent?.trim() === OTHER_AGENT.name)!
                    .click(),
        },
        {
            link: 'the agent link of an instruction preview',
            open: (store: AgentsPageStore) => store.selectAgentDoc(OTHER_AGENT.id, 0),
            follow: (fixture: PageFixture) =>
                fixture.debugElement
                    .query(By.css('app-agent-doc-preview'))
                    .triggerEventHandler('openAgent', OTHER_AGENT.id),
        },
    ];

    it.each(AGENT_LINKS)('waits for the agent save under way before following $link', async ({ open, follow }) => {
        const { fixture, store } = renderEdited(false, true);
        descriptionInput(fixture).blur();
        const save = expectAgentRequest('PATCH', `${AGENTS_URL}${AGENT.id}/`);
        open(store);
        await settle(fixture);

        follow(fixture);
        await settle(fixture);
        expect(shows(fixture, OTHER_AGENT)).toBe(false);

        save.flush({ ...AGENT, description: 'Reads CVs' });
        await settle(fixture);
        expect(shows(fixture, OTHER_AGENT)).toBe(true);
    });

    /** Links inside the agent editor that open something else; `opened` says whether it is shown. */
    const EDITOR_LINKS = [
        {
            link: 'one of its instructions',
            follow: (fixture: PageFixture) =>
                fixture.debugElement
                    .query(By.css('app-agent-instructions-list'))
                    .triggerEventHandler('openInstruction', { index: 0, edit: false }),
            opened: (fixture: PageFixture) => {
                fixture.detectChanges();
                return host(fixture).querySelector('app-agent-doc-preview') !== null;
            },
        },
        {
            link: 'the source of a shared surface',
            follow: (fixture: PageFixture) =>
                fixture.debugElement
                    .query(By.css('app-agent-surfaces-panel'))
                    .triggerEventHandler('openSource', SHARED_SURFACE.id),
            opened: (fixture: PageFixture) => {
                fixture.detectChanges();
                return host(fixture).querySelector('app-surface-detail') !== null;
            },
        },
    ];

    /** The editor with "About this Agent" saved on blur, the save still under way. */
    async function renderSaving(): Promise<ReturnType<typeof renderEdited> & { save: TestRequest }> {
        const rendered = renderEdited(false, true);
        descriptionInput(rendered.fixture).blur();
        const save = expectAgentRequest('PATCH', `${AGENTS_URL}${AGENT.id}/`);
        await settle(rendered.fixture);
        return { ...rendered, save };
    }

    it.each(EDITOR_LINKS)('waits for the agent save under way before opening $link', async ({ follow, opened }) => {
        const { fixture, save } = await renderSaving();

        follow(fixture);
        await settle(fixture);
        expect(opened(fixture)).toBe(false);

        save.flush({ ...AGENT_ON_SERVER, description: 'Reads CVs' });
        await settle(fixture);
        expect(opened(fixture)).toBe(true);
    });

    it.each(EDITOR_LINKS)(
        'asks what to do when that save fails, instead of opening $link',
        async ({ follow, opened }) => {
            const { fixture, overlay, save } = await renderSaving();

            follow(fixture);
            save.flush({ detail: 'Name is taken' }, SAVE_FAILED);
            await settle(fixture);

            expect(dialogText(overlay).title).toBe("Couldn't save your changes");
            expect(opened(fixture)).toBe(false);
        }
    );

    it.each(LEAVE_FOR_ANOTHER_PLACE)(
        'creates a named draft without asking, and goes where the user was going once it exists, on $way',
        async ({ start }) => {
            const { fixture, overlay } = renderNamedDraft();

            const { left } = start(fixture);
            const create = expectAgentRequest('POST', AGENTS_URL);
            await settle(fixture);

            expect(create.request.body).toMatchObject({ name: DRAFT_NAME, description: 'Reads CVs' });
            expect(dialogText(overlay).title).toBe('');
            expect(left()).not.toBe(true);

            create.flush({ ...AGENT, id: 9, name: DRAFT_NAME, description: 'Reads CVs' });
            await settle(fixture);

            expect(left()).toBe(true);
        }
    );

    it.each(LEAVE_FOR_ANOTHER_PLACE)(
        'keeps a named draft that fails to be created on Keep Editing, on $way',
        async ({ start }) => {
            const { fixture, overlay } = renderNamedDraft();

            const { left } = start(fixture);
            expectAgentRequest('POST', AGENTS_URL).flush({ detail: 'Name is taken' }, SAVE_FAILED);
            await settle(fixture);
            expect(dialogText(overlay).title).toBe("Couldn't save your changes");
            await choose(fixture, overlay, 'Keep Editing');

            expect(left()).toBe(false);
            expect(nameInput(fixture).value).toBe(DRAFT_NAME);
            TestBed.inject(HttpTestingController).expectNone({ method: 'POST', url: AGENTS_URL });
        }
    );

    it('waits for a save under way, then saves what was typed meanwhile before going', async () => {
        const { fixture } = renderEdited(false, true);
        descriptionInput(fixture).blur();
        const firstSave = expectAgentRequest('PATCH', `${AGENTS_URL}${AGENT.id}/`);
        await settle(fixture);
        descriptionInput(fixture).focus();
        type(fixture, descriptionInput(fixture), 'Reads CVs and cover letters');

        clickAgent(fixture, OTHER_AGENT);
        TestBed.inject(HttpTestingController).expectNone({ method: 'PATCH', url: `${AGENTS_URL}${AGENT.id}/` });
        firstSave.flush({ ...AGENT, description: 'Reads CVs' });
        await settle(fixture);
        const secondSave = expectAgentRequest('PATCH', `${AGENTS_URL}${AGENT.id}/`);

        expect(secondSave.request.body).toMatchObject({ description: 'Reads CVs and cover letters' });
        expect(shows(fixture, OTHER_AGENT)).toBe(false);

        secondSave.flush({ ...AGENT, description: 'Reads CVs and cover letters' });
        await settle(fixture);

        expect(shows(fixture, OTHER_AGENT)).toBe(true);
    });

    it('creates a draft once when the user types while it is being created, then clicks away', async () => {
        const { fixture } = renderNamedDraft();
        nameInput(fixture).blur();
        const create = expectAgentRequest('POST', AGENTS_URL);
        await settle(fixture);
        descriptionInput(fixture).focus();
        type(fixture, descriptionInput(fixture), 'Reads CVs and cover letters');

        clickAgent(fixture, OTHER_AGENT);
        create.flush({ ...AGENT, id: 9, name: DRAFT_NAME, description: 'Reads CVs' });
        await settle(fixture);

        TestBed.inject(HttpTestingController).expectNone({ method: 'POST', url: AGENTS_URL });
        expect(shows(fixture, OTHER_AGENT)).toBe(true);
    });

    it('answers a route leave still waiting for the save with "stay" once another agent is clicked, and follows the click', async () => {
        const { fixture } = renderEdited(false, true);
        const routeWent = leaveRoute(fixture);
        const save = expectAgentRequest('PATCH', `${AGENTS_URL}${AGENT.id}/`);
        await settle(fixture);

        clickAgent(fixture, OTHER_AGENT);

        expect(routeWent()).toBe(false);
        save.flush({ ...AGENT, description: 'Reads CVs' });
        await settle(fixture);
        expect(shows(fixture, OTHER_AGENT)).toBe(true);
    });

    it('drops a click still waiting for the save once the route is left', async () => {
        const { fixture } = renderEdited(false, true);
        clickAgent(fixture, OTHER_AGENT);
        const save = expectAgentRequest('PATCH', `${AGENTS_URL}${AGENT.id}/`);
        await settle(fixture);
        const routeWent = leaveRoute(fixture);

        save.flush({ ...AGENT, description: 'Reads CVs' });
        await settle(fixture);

        expect(routeWent()).toBe(true);
        expect(shows(fixture, AGENT)).toBe(true);
    });

    it('does not follow a click once the page is gone, when the save it waited for lands', () => {
        const { fixture, store } = renderEdited(false, true);
        clickAgent(fixture, OTHER_AGENT);
        const save = expectAgentRequest('PATCH', `${AGENTS_URL}${AGENT.id}/`);

        fixture.destroy();
        save.flush({ ...AGENT, description: 'Reads CVs' });

        expect(store.selectedAgent()?.id).toBe(AGENT.id);
    });

    it("asks to discard a saved agent's edits that can't be saved, a name over the limit, and sends nothing", async () => {
        const { fixture, overlay } = renderEdited(false, true);
        nameInput(fixture).focus();
        expectAgentRequest('PATCH', `${AGENTS_URL}${AGENT.id}/`).flush({ ...AGENT, description: 'Reads CVs' });
        await settle(fixture);
        type(fixture, nameInput(fixture), 'x'.repeat(256));

        const went = leaveRoute(fixture);
        await fixture.whenStable();

        expect(dialogText(overlay)).toEqual({
            title: 'Changes not saved',
            message: "These changes can't be saved as they are. Fix the name to save them, or discard them.",
            buttons: ['Discard & Leave', 'Keep Editing'],
        });
        TestBed.inject(HttpTestingController).expectNone({ method: 'PATCH', url: `${AGENTS_URL}${AGENT.id}/` });

        await choose(fixture, overlay, 'Discard & Leave');

        expect(went()).toBe(true);
    });

    it('asks to discard a nameless draft with a model picked, and creates nothing when the dialog takes the focus', async () => {
        const { fixture, overlay } = renderEdited(true, true);
        const primaryModel = fixture.debugElement.query(By.directive(LlmModelSelectorStubComponent));
        (primaryModel.componentInstance as LlmModelSelectorStubComponent).pick(1);
        nameInput(fixture).focus();

        leaveRoute(fixture);
        await fixture.whenStable();

        expect(dialogText(overlay).title).toBe('Agent not created');
        expect(document.activeElement).not.toBe(nameInput(fixture));
        TestBed.inject(HttpTestingController).expectNone({ method: 'POST', url: AGENTS_URL });
    });

    it('leaves a saved agent without asking once its edit is changed back', () => {
        const { fixture } = renderEdited(false);

        type(fixture, descriptionInput(fixture), AGENT.description);

        expect(fixture.componentInstance.canDeactivate()).toBe(true);
    });

    it('leaves a saved agent without asking once an emptied name has been put back', () => {
        const { fixture } = renderEdited(false);
        type(fixture, descriptionInput(fixture), AGENT.description);

        nameInput(fixture).focus();
        type(fixture, nameInput(fixture), '');
        nameInput(fixture).blur();
        fixture.detectChanges();

        expect(nameInput(fixture).value).toBe(AGENT.name);
        expect(fixture.componentInstance.canDeactivate()).toBe(true);
    });

    it('starts an empty draft on Discard & Leave into another Add Agent, even after Keep Editing', async () => {
        const { fixture, overlay } = renderEdited(true, true);
        fixture.componentInstance.onAddAgent();
        await fixture.whenStable();
        await choose(fixture, overlay, 'Keep Editing');
        expect(nameError(fixture)).toBe('Agent name is required');

        fixture.componentInstance.onAddAgent();
        await fixture.whenStable();
        await choose(fixture, overlay, 'Discard & Leave');

        expect(descriptionInput(fixture).value).toBe('');
        expect(nameError(fixture)).toBeNull();
        expect(fixture.componentInstance.canDeactivate()).toBe(true);
    });
});
