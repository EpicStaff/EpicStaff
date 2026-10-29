import { OverlayContainer } from '@angular/cdk/overlay';
import { HttpErrorResponse } from '@angular/common/http';
import { signal } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { CreateLabelRequest, LabelColor, LabelDto } from '@shared/models';
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

/** Focus leaves the input for `next` (nothing focusable when null). */
function leave(
    fixture: ComponentFixture<AgentsSectionComponent>,
    input: HTMLInputElement,
    next: HTMLElement | null = null
): void {
    input.dispatchEvent(new FocusEvent('focusout', { bubbles: true, relatedTarget: next }));
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

    it('keeps the draft while a color is picked, then saves the name with that color', () => {
        const { fixture, store, api, input } = render();
        const host = fixture.nativeElement as HTMLElement;
        const pickerTrigger = host.querySelector<HTMLButtonElement>('.color-trigger-btn')!;

        type(fixture, input()!, 'Sales');
        leave(fixture, input()!, pickerTrigger);
        expect(api.createdNames).toEqual([]);

        // Opening the picker moves focus from its trigger into the overlay, outside this field's DOM.
        pickerTrigger.focus();
        pickerTrigger.click();
        fixture.detectChanges();
        const overlay = TestBed.inject(OverlayContainer).getContainerElement();
        expect(overlay.contains(document.activeElement)).toBe(true);
        expect(api.createdNames).toEqual([]);

        overlay.querySelector<HTMLButtonElement>(`.color-option-btn[title="${LabelColor.Green}"]`)!.click();
        fixture.detectChanges();
        leave(fixture, input()!);

        expect(store.groups().map((group) => [group.name, group.metadata.color])).toEqual([
            ['Sales', LabelColor.Green],
        ]);
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
