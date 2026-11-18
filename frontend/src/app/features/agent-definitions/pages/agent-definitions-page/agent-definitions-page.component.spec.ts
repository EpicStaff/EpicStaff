import { CdkTrapFocus } from '@angular/cdk/a11y';
import { Dialog } from '@angular/cdk/dialog';
import { OverlayContainer, OverlayModule } from '@angular/cdk/overlay';
import { provideHttpClient } from '@angular/common/http';
import { provideHttpClientTesting } from '@angular/common/http/testing';
import { Component, CUSTOM_ELEMENTS_SCHEMA, forwardRef, input, signal, WritableSignal } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { ControlValueAccessor, NG_VALUE_ACCESSOR, ReactiveFormsModule } from '@angular/forms';
import { ActivatedRoute, convertToParamMap, Router } from '@angular/router';
import {
    AppSvgIconComponent,
    AuthorshipDetailsDialogService,
    ConfirmationDialogService,
    UnsavedChangesDialogService,
} from '@shared/components';
import { EnterBlurDirective, HasPermissionDirective } from '@shared/directives';
import { ActionCode, ResourceCode } from '@shared/models';
import { of } from 'rxjs';

import { tourAnchorSelector } from '../../../../core/guided-tour';
import { PermissionsService } from '../../../../services/auth/permissions.service';
import { ProfileService } from '../../../../services/auth/profile.service';
import { ToastService } from '../../../../services/notifications';
import { CREATE_AGENT_TOUR_ANCHORS } from '../../../create-agent-tour/create-agent-tour-anchors';
import { StorageTreeFacade } from '../../../files/services/storage-tree-facade.service';
import { AgentDefinition } from '../../models/agent-definition.model';
import { Surface } from '../../models/surface.model';
import { AgentDefinitionsApiService } from '../../services/agent-definitions-api.service';
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

    writeValue(): void {}

    registerOnChange(): void {}

    registerOnTouched(): void {}
}

describe('AgentDefinitionsPageComponent leaving unsaved agent edits', () => {
    type PageFixture = ComponentFixture<AgentDefinitionsPageComponent>;

    /**
     * The page with the real agent editor, on a draft (`drafting`) or on `AGENT`, with an edit not saved yet.
     * `realStore` runs the draft through the real page store, over a fake API with no agents.
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
                { provide: ToastService, useValue: { info: vi.fn() } },
                { provide: AgentDefinitionsApiService, useValue: { getAgentDefinitions: () => of([]) } },
                { provide: SurfacesApiService, useValue: { getSurfaces: () => of([]) } },
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
        if (realStore) fixture.debugElement.injector.get(AgentsPageStore).beginCreateAgent();
        fixture.detectChanges();
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
        {
            way: 'leaving the route',
            start: (fixture: PageFixture) => {
                let went: boolean | undefined;
                const answer = fixture.componentInstance.canDeactivate();
                if (typeof answer === 'boolean') went = answer;
                else answer.subscribe((leave) => (went = leave));
                return { left: (): boolean | undefined => went };
            },
        },
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

    it('asks about a saved agent without claiming it was never created, and leaves its name alone', async () => {
        const { fixture, overlay } = renderEdited(false);

        fixture.componentInstance.onAddAgent();
        await fixture.whenStable();

        expect(dialogText(overlay)).toEqual({
            title: 'Unsaved Changes',
            message: 'You have unsaved changes in this agent.',
            buttons: ['Discard & Leave', 'Keep Editing'],
        });

        await choose(fixture, overlay, 'Keep Editing');

        expect(document.activeElement).not.toBe(nameInput(fixture));
        expect(nameError(fixture)).toBeNull();
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
