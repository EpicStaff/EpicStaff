import { signal } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { LabelDto } from '@shared/models';
import { of } from 'rxjs';

import { PermissionsService } from '../../../../../../../services/auth/permissions.service';
import { ProfileService } from '../../../../../../../services/auth/profile.service';
import { ToastService } from '../../../../../../../services/notifications';
import { Surface } from '../../../../../models/surface.model';
import { AgentDefinitionsApiService } from '../../../../../services/agent-definitions-api.service';
import { AgentGroupsApiService } from '../../../../../services/agent-groups-api.service';
import { AgentsPageStore } from '../../../../../services/agents-page-store.service';
import { SurfaceCatalogsStore } from '../../../../../services/surface-catalogs-store.service';
import { SurfacesApiService } from '../../../../../services/surfaces-api.service';
import { AgentsSectionComponent } from '../agents-section/agents-section.component';
import { SurfacesSectionComponent } from './surfaces-section.component';

const SHARED_SURFACE = { id: 10, name: 'CRM access', group: null, owner_agent: null } as Partial<Surface> as Surface;

/** A surface already in the group: the Shared Surfaces section lists only groups that hold one. */
const surfacesInGroups = (group: LabelDto): Surface[] => [
    { id: 11, name: 'Billing', group: group.id, owner_agent: null } as Partial<Surface> as Surface,
];

class ResizeObserverStub {
    observe(): void {}
    unobserve(): void {}
    disconnect(): void {}
}

function render(initialGroups: LabelDto[] = []): {
    store: AgentsPageStore;
    patches: { id: number; body: unknown }[];
    agentsInput: () => HTMLInputElement | null;
    surfacesInput: () => HTMLInputElement | null;
    surfacesHost: HTMLElement;
    detect: () => void;
    name: (value: string) => void;
} {
    const patches: { id: number; body: unknown }[] = [];
    let groups: LabelDto[] = initialGroups;
    TestBed.configureTestingModule({
        providers: [
            AgentsPageStore,
            {
                provide: AgentGroupsApiService,
                useValue: {
                    getLabels: () => of(groups),
                    createLabel: (body: { name: string }) => {
                        const created = { id: 1, name: body.name, parent: null, full_path: body.name } as LabelDto;
                        groups = [created];
                        return of(created);
                    },
                },
            },
            { provide: AgentDefinitionsApiService, useValue: { getAgentDefinitions: () => of([]) } },
            {
                provide: SurfacesApiService,
                useValue: {
                    getSurfaces: () =>
                        of(
                            initialGroups.length > 0
                                ? [SHARED_SURFACE, ...surfacesInGroups(initialGroups[0])]
                                : [SHARED_SURFACE]
                        ),
                    partialUpdate: (id: number, body: { group: number | null }) => {
                        patches.push({ id, body });
                        return of({ ...SHARED_SURFACE, group: body.group });
                    },
                },
            },
            { provide: PermissionsService, useValue: { can: () => true } },
            { provide: ProfileService, useValue: { currentUserSignal: signal({ id: 7 }) } },
            { provide: ToastService, useValue: {} },
            { provide: SurfaceCatalogsStore, useValue: {} },
        ],
    });
    const store = TestBed.inject(AgentsPageStore);
    store.load();
    const agents: ComponentFixture<AgentsSectionComponent> = TestBed.createComponent(AgentsSectionComponent);
    const surfaces: ComponentFixture<SurfacesSectionComponent> = TestBed.createComponent(SurfacesSectionComponent);
    const inputIn = (fixture: ComponentFixture<unknown>): HTMLInputElement | null =>
        (fixture.nativeElement as HTMLElement).querySelector<HTMLInputElement>('input[aria-label="New group name"]');
    const detect = (): void => {
        agents.detectChanges();
        surfaces.detectChanges();
    };
    detect();
    return {
        store,
        patches,
        surfacesHost: surfaces.nativeElement as HTMLElement,
        detect,
        agentsInput: () => {
            detect();
            return inputIn(agents);
        },
        surfacesInput: () => {
            detect();
            return inputIn(surfaces);
        },
        name: (value) => {
            const input = inputIn(surfaces)!;
            input.value = value;
            input.dispatchEvent(new Event('input'));
            input.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter' }));
            detect();
        },
    };
}

describe('New group input placement', () => {
    beforeEach(() => {
        localStorage.clear();
        vi.stubGlobal('ResizeObserver', ResizeObserverStub);
    });
    afterEach(() => {
        localStorage.clear();
        vi.unstubAllGlobals();
        vi.useRealTimers();
    });

    it('is shown in Shared Surfaces only, when started from a shared surface row', () => {
        const { store, agentsInput, surfacesInput } = render();

        store.startNewGroup({ kind: 'surface', id: SHARED_SURFACE.id });

        expect(surfacesInput()).not.toBeNull();
        expect(agentsInput()).toBeNull();
    });

    it('is shown in Agents only, when started from the Agents section', () => {
        const { store, agentsInput, surfacesInput } = render();

        store.startNewGroup();

        expect(agentsInput()).not.toBeNull();
        expect(surfacesInput()).toBeNull();
    });

    it('is a single draft: starting one in the other section moves it there', () => {
        const { store, agentsInput, surfacesInput } = render();

        store.startNewGroup();
        store.startNewGroup({ kind: 'surface', id: SHARED_SURFACE.id });

        expect(surfacesInput()).not.toBeNull();
        expect(agentsInput()).toBeNull();
    });

    it('creates the group from the Shared Surfaces input and moves the surface into it', () => {
        vi.useFakeTimers();
        const { store, patches, surfacesInput, name } = render();
        store.startNewGroup({ kind: 'surface', id: SHARED_SURFACE.id });
        expect(surfacesInput()).not.toBeNull();

        name('Sales');
        vi.advanceTimersByTime(1000);

        expect(store.groups().map((group) => group.name)).toEqual(['Sales']);
        expect(patches).toEqual([{ id: SHARED_SURFACE.id, body: { group: 1 } }]);
        expect(surfacesInput()).toBeNull();
    });
});

describe('Dragging a shared surface into a group', () => {
    const SALES = { id: 4, name: 'Sales', parent: null, full_path: 'Sales' } as LabelDto;

    beforeEach(() => {
        localStorage.clear();
        vi.stubGlobal('ResizeObserver', ResizeObserverStub);
    });
    afterEach(() => {
        localStorage.clear();
        vi.unstubAllGlobals();
        vi.useRealTimers();
    });

    it('moves the surface into the group, and the drag effects agree so the browser delivers the drop', () => {
        vi.useFakeTimers();
        const { patches, surfacesHost, detect } = render([SALES]);
        const transfer = { effectAllowed: 'uninitialized', dropEffect: 'none', setData: () => undefined };
        const row = [...surfacesHost.querySelectorAll<HTMLElement>('.row--surface')].find((element) =>
            element.textContent.includes('CRM access')
        )!;
        const groupBlock = surfacesHost.querySelector<HTMLElement>('[role="group"]')!;

        const dragStart = new Event('dragstart', { bubbles: true, cancelable: true });
        Object.defineProperty(dragStart, 'dataTransfer', { value: transfer });
        row.dispatchEvent(dragStart);
        detect();
        const over = new Event('dragover', { bubbles: true, cancelable: true });
        Object.defineProperty(over, 'dataTransfer', { value: transfer });
        groupBlock.dispatchEvent(over);

        // A browser drops only when the target's effect is one the source allows.
        expect(['copyMove', 'all']).toContain(transfer.effectAllowed);
        expect(over.defaultPrevented).toBe(true);
        expect(['copy', 'move']).toContain(transfer.dropEffect);

        const drop = new Event('drop', { bubbles: true, cancelable: true });
        Object.defineProperty(drop, 'dataTransfer', { value: transfer });
        groupBlock.dispatchEvent(drop);
        vi.advanceTimersByTime(1000);

        expect(patches).toEqual([{ id: SHARED_SURFACE.id, body: { group: SALES.id } }]);
    });
});
