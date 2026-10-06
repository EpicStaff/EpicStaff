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

import { PermissionsService } from '../../../../services/auth/permissions.service';
import { StorageTreeFacade } from '../../../files/services/storage-tree-facade.service';
import { AgentDefinition } from '../../models/agent-definition.model';
import { AgentsPageStore } from '../../services/agents-page-store.service';
import { SurfaceCatalogsStore } from '../../services/surface-catalogs-store.service';
import { AgentDefinitionsPageComponent } from './agent-definitions-page.component';
import { DetailHeaderComponent } from './components/detail-header/detail-header.component';

const AGENT: AgentDefinition = {
    id: 3,
    org: 1,
    name: 'CV Processor',
    description: '',
    instructions: '',
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
    max_tool_calls: null,
    tool_timeout: null,
    max_consecutive_failures: null,
    schema_max_retries: null,
    created_at: '2026-03-12T13:28:23Z',
    created_by: { id: 1, display_name: 'Ivan Bohun', avatar_url: null },
    last_edited_by: { id: 2, display_name: 'Olena Petrenko', avatar_url: null },
    last_edited_at: '2026-03-13T09:00:00Z',
};

/** Just enough of the page store to render the agent editor with `AGENT` selected. */
function agentSelectedStore(): Partial<Record<keyof AgentsPageStore, unknown>> {
    return {
        load: () => undefined,
        loading: signal(false),
        selectedNode: signal({ kind: 'agent', id: AGENT.id }),
        showSidebar: signal(false),
        isStorageSelected: signal(false),
        selectedAgentDoc: signal(null),
        selectedSurfaceView: signal(null),
        selectedAgent: signal(AGENT),
        selectedSurface: signal(null),
        surfacesOnlyAgent: signal(null),
        isDraftingAgent: signal(false),
        isDraftingSurface: signal(false),
        saving: signal(false),
        agents: signal([AGENT]),
        surfaces: signal([]),
        agentSaveErrorTick: signal(0),
        surfaceSaveError: signal(null),
        surfaceCreateErrorTick: signal(0),
        sharedSurfaceIdSet: signal(new Set<number>()),
        isBootDoc: () => false,
    };
}

function render(canWrite: boolean): {
    fixture: ComponentFixture<AgentDefinitionsPageComponent>;
    host: HTMLElement;
    overlay: HTMLElement;
} {
    TestBed.configureTestingModule({
        providers: [
            {
                provide: PermissionsService,
                useValue: { active: signal(null), can: () => canWrite, canAny: () => canWrite },
            },
            { provide: ActivatedRoute, useValue: { snapshot: { queryParamMap: convertToParamMap({}) } } },
            { provide: Router, useValue: { navigate: () => Promise.resolve(true) } },
            { provide: UnsavedChangesDialogService, useValue: {} },
            { provide: ConfirmationDialogService, useValue: {} },
        ],
    });
    // Only the editor header is under test: the explorer and editor panes stay unrendered custom elements.
    TestBed.overrideComponent(AgentDefinitionsPageComponent, {
        set: {
            imports: [DetailHeaderComponent, AppSvgIconComponent, OverlayModule, HasPermissionDirective],
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

function openMenu(fixture: ComponentFixture<AgentDefinitionsPageComponent>): void {
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
