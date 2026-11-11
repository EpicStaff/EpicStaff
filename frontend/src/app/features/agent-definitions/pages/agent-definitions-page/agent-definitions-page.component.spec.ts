import { CdkTrapFocus } from '@angular/cdk/a11y';
import { Dialog } from '@angular/cdk/dialog';
import { OverlayContainer, OverlayModule } from '@angular/cdk/overlay';
import { CUSTOM_ELEMENTS_SCHEMA, signal, WritableSignal } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { ActivatedRoute, convertToParamMap, Router } from '@angular/router';
import {
    AppSvgIconComponent,
    AuthorshipDetailsDialogService,
    ConfirmationDialogService,
    UnsavedChangesDialogService,
} from '@shared/components';
import { HasPermissionDirective } from '@shared/directives';
import { ActionCode, ResourceCode } from '@shared/models';
import { of } from 'rxjs';

import { tourAnchorSelector } from '../../../../core/guided-tour';
import { PermissionsService } from '../../../../services/auth/permissions.service';
import { CREATE_AGENT_TOUR_ANCHORS } from '../../../create-agent-tour/create-agent-tour-anchors';
import { StorageTreeFacade } from '../../../files/services/storage-tree-facade.service';
import { AgentDefinition } from '../../models/agent-definition.model';
import { Surface } from '../../models/surface.model';
import { AgentGroupsStorageService } from '../../services/agent-groups-storage.service';
import { AgentsPageStore } from '../../services/agents-page-store.service';
import { SurfaceCatalogsStore } from '../../services/surface-catalogs-store.service';
import { AgentDefinitionsPageComponent } from './agent-definitions-page.component';
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
        updateAgent: vi.fn(),
        saveNewAgent: vi.fn(),
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

function render(grants: Grants): {
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
            { provide: ActivatedRoute, useValue: { snapshot: { queryParamMap: convertToParamMap({}) } } },
            { provide: Router, useValue: { navigate: () => Promise.resolve(true) } },
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

        // The stubbed UnsavedChangesDialogService has no confirmUnsavedChanges: prompting would throw.
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
