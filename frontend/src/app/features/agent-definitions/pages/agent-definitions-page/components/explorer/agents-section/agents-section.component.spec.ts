import { HttpErrorResponse } from '@angular/common/http';
import { signal } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { CreateLabelRequest, LabelDto } from '@shared/models';
import { Observable, of, throwError } from 'rxjs';

import { PermissionsService } from '../../../../../../../services/auth/permissions.service';
import { ProfileService } from '../../../../../../../services/auth/profile.service';
import { ToastService } from '../../../../../../../services/notifications';
import { AgentDefinitionsApiService } from '../../../../../services/agent-definitions-api.service';
import { AgentGroupsApiService } from '../../../../../services/agent-groups-api.service';
import { AgentsPageStore } from '../../../../../services/agents-page-store.service';
import { SurfaceCatalogsStore } from '../../../../../services/surface-catalogs-store.service';
import { SurfacesApiService } from '../../../../../services/surfaces-api.service';
import { AgentsSectionComponent } from './agents-section.component';

const NAME_TAKEN = 'A group with this name already exists';

/** In-memory `agent-labels/` endpoint: keeps created groups and can reject the next creates. */
class FakeGroupsApi {
    groups: LabelDto[] = [];
    createdNames: string[] = [];
    rejectCreates = false;

    getLabels(): Observable<LabelDto[]> {
        return of(this.groups);
    }

    createLabel(body: CreateLabelRequest): Observable<LabelDto> {
        this.createdNames.push(body.name);
        if (this.rejectCreates) return throwError(() => new HttpErrorResponse({ status: 400, error: NAME_TAKEN }));
        const created: LabelDto = {
            id: this.groups.length + 1,
            name: body.name,
            parent: null,
            full_path: body.name,
            created_at: '',
            metadata: body.metadata ?? {},
        };
        this.groups = [...this.groups, created];
        return of(created);
    }
}

function render(): {
    fixture: ComponentFixture<AgentsSectionComponent>;
    store: AgentsPageStore;
    api: FakeGroupsApi;
    input: () => HTMLInputElement | null;
    error: () => string | null;
} {
    const api = new FakeGroupsApi();
    TestBed.configureTestingModule({
        providers: [
            AgentsPageStore,
            { provide: AgentGroupsApiService, useValue: api },
            { provide: AgentDefinitionsApiService, useValue: { getAgentDefinitions: () => of([]) } },
            { provide: SurfacesApiService, useValue: { getSurfaces: () => of([]) } },
            { provide: PermissionsService, useValue: { can: () => true } },
            { provide: ProfileService, useValue: { currentUserSignal: signal({ id: 7 }) } },
            { provide: ToastService, useValue: {} },
            { provide: SurfaceCatalogsStore, useValue: {} },
        ],
    });
    const store = TestBed.inject(AgentsPageStore);
    store.load();
    const fixture = TestBed.createComponent(AgentsSectionComponent);
    const host = fixture.nativeElement as HTMLElement;
    store.startNewGroup();
    fixture.detectChanges();
    return {
        fixture,
        store,
        api,
        input: () => host.querySelector<HTMLInputElement>('input[aria-label="New group name"]'),
        error: () => host.querySelector('[role="alert"]')?.textContent?.trim() ?? null,
    };
}

function type(fixture: ComponentFixture<AgentsSectionComponent>, input: HTMLInputElement, value: string): void {
    input.value = value;
    input.dispatchEvent(new Event('input'));
    fixture.detectChanges();
}

/** Focus leaves the input. */
function leave(fixture: ComponentFixture<AgentsSectionComponent>, input: HTMLInputElement): void {
    input.dispatchEvent(new FocusEvent('blur'));
    fixture.detectChanges();
}

const groupNames = (store: AgentsPageStore): string[] => store.groups().map((group) => group.name);

describe('AgentsSectionComponent new group input', () => {
    beforeEach(() => localStorage.clear());
    afterEach(() => localStorage.clear());

    it('saves a typed name when focus leaves the input, and closes the input', () => {
        const { fixture, store, input } = render();

        type(fixture, input()!, 'Sales');
        leave(fixture, input()!);

        expect(groupNames(store)).toEqual(['Sales']);
        expect(input()).toBeNull();
    });

    it('cancels without saving when focus leaves an empty input', () => {
        const { fixture, store, api, input } = render();

        type(fixture, input()!, '   ');
        leave(fixture, input()!);

        expect(api.createdNames).toEqual([]);
        expect(groupNames(store)).toEqual([]);
        expect(input()).toBeNull();
    });

    it('does not resubmit a rejected name on blur, and retries once the name is edited', () => {
        const { fixture, store, api, input, error } = render();
        api.rejectCreates = true;

        type(fixture, input()!, 'Sales');
        leave(fixture, input()!);
        leave(fixture, input()!);

        expect(api.createdNames).toEqual(['Sales']);
        expect(error()).toBe(NAME_TAKEN);
        expect(input()).not.toBeNull();

        api.rejectCreates = false;
        type(fixture, input()!, 'Sales EMEA');
        expect(error()).toBeNull();
        leave(fixture, input()!);

        expect(groupNames(store)).toEqual(['Sales EMEA']);
        expect(input()).toBeNull();
    });

    it.each([
        { how: 'Enter', refocused: true },
        { how: 'blur', refocused: false },
    ])('after a rejected save by $how, focus returns to the input: $refocused', async ({ how, refocused }) => {
        const { fixture, api, input } = render();
        api.rejectCreates = true;
        const elsewhere = document.body.appendChild(document.createElement('button'));

        type(fixture, input()!, 'Sales');
        if (how === 'Enter') {
            input()!.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter' }));
            fixture.detectChanges();
        } else {
            elsewhere.focus();
            leave(fixture, input()!);
        }
        await new Promise((resolve) => setTimeout(resolve));

        expect(document.activeElement === input()).toBe(refocused);
        elsewhere.remove();
    });
});

describe('AgentsSectionComponent export bar', () => {
    class ResizeObserverStub {
        observe(): void {}
        unobserve(): void {}
        disconnect(): void {}
    }

    beforeEach(() => vi.stubGlobal('ResizeObserver', ResizeObserverStub));
    afterEach(() => vi.unstubAllGlobals());

    const AGENTS = [
        { id: 1, name: 'Alpha', group: null, instruction_list: [], default_surfaces: [] },
        { id: 2, name: 'Beta', group: null, instruction_list: [], default_surfaces: [] },
    ];

    function renderBar(): {
        fixture: ComponentFixture<AgentsSectionComponent>;
        store: AgentsPageStore;
        buttons: () => string[];
        click: (label: string) => void;
    } {
        TestBed.configureTestingModule({
            providers: [
                AgentsPageStore,
                { provide: AgentGroupsApiService, useValue: new FakeGroupsApi() },
                { provide: AgentDefinitionsApiService, useValue: { getAgentDefinitions: () => of(AGENTS) } },
                { provide: SurfacesApiService, useValue: { getSurfaces: () => of([]) } },
                { provide: PermissionsService, useValue: { can: () => true } },
                { provide: ProfileService, useValue: { currentUserSignal: signal({ id: 7 }) } },
                { provide: ToastService, useValue: {} },
                { provide: SurfaceCatalogsStore, useValue: {} },
            ],
        });
        const store = TestBed.inject(AgentsPageStore);
        store.load();
        const fixture = TestBed.createComponent(AgentsSectionComponent);
        fixture.detectChanges();
        const host = fixture.nativeElement as HTMLElement;
        const barButtons = (): HTMLButtonElement[] => [
            ...host.querySelectorAll<HTMLButtonElement>('.export-bar button'),
        ];
        return {
            fixture,
            store,
            buttons: () =>
                barButtons().map((button) => `${button.textContent.trim()}${button.disabled ? ' (disabled)' : ''}`),
            click: (label) => {
                barButtons()
                    .find((button) => button.textContent.trim() === label)!
                    .click();
                fixture.detectChanges();
            },
        };
    }

    it('shows no bar outside export mode', () => {
        const { buttons } = renderBar();

        expect(buttons()).toEqual([]);
    });

    it('offers Cancel, Select all and a disabled Export 0 once the export starts', () => {
        const { fixture, store, buttons } = renderBar();

        store.startAgentExport();
        fixture.detectChanges();

        expect(buttons()).toEqual(['Cancel', 'Select all', 'Export 0 (disabled)']);
    });

    it('counts the ticked agents on the Export button', () => {
        const { fixture, store, buttons } = renderBar();
        store.startAgentExport();
        store.toggleAgentSelection(2);
        fixture.detectChanges();

        expect(buttons()).toEqual(['Cancel', 'Select all', 'Export 1']);
    });

    it('ticks every agent on Select all and clears them on Deselect all', () => {
        const { fixture, store, buttons, click } = renderBar();
        store.startAgentExport();
        fixture.detectChanges();

        click('Select all');
        expect([...store.selectedAgentIds()]).toEqual([1, 2]);
        expect(buttons()).toEqual(['Cancel', 'Deselect all', 'Export 2']);

        click('Deselect all');
        expect(store.selectedAgentIds().size).toBe(0);
    });

    it('leaves export mode with nothing ticked on Cancel', () => {
        const { fixture, store, buttons, click } = renderBar();
        store.startAgentExport();
        store.toggleAgentSelection(1);
        fixture.detectChanges();

        click('Cancel');

        expect(store.agentExportMode()).toBe(false);
        expect(store.selectedAgentIds().size).toBe(0);
        expect(buttons()).toEqual([]);
    });
});
