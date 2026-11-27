import { provideHttpClient, withInterceptors } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting, TestRequest } from '@angular/common/http/testing';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { ShortcutSettings } from '@shared/models';

import {
    activeOrgInterceptor,
    ORGANIZATION_HEADER,
} from '../../../../../../../core/interceptors/active-org.interceptor';
import { ActiveOrgService } from '../../../../../../../services/auth/active-org.service';
import { ProfileService } from '../../../../../../../services/auth/profile.service';
import {
    API_URL,
    memberOf,
    ORGANIZATION_A,
    ORGANIZATION_B,
    PROFILE_URL,
} from '../../../../../../../services/auth/testing/current-user-fixtures';
import { ConfigService } from '../../../../../../../services/config';
import { ResizeObserverStub } from '../../../../../../../visual-programming/components/shortcuts-editor/testing/shortcuts-editor.fixture';
import { ShortcutsSectionComponent } from './shortcuts-section.component';

const GRAPH_LIGHT_URL = '/api/graph-light/';

const SAVED_SHORTCUTS: ShortcutSettings = {
    custom: [
        { action: 'node.subgraph', keys: 'Alt+Digit1', params: { flowId: 12 } },
        { action: 'node.subgraph', keys: 'Alt+Digit2', params: { flowId: 34 } },
    ],
    // A changed node key, so the user has something to reset to the defaults.
    overrides: { 'node.python': 'Alt+KeyQ' },
};

describe('ShortcutsSectionComponent', () => {
    let fixture: ComponentFixture<ShortcutsSectionComponent>;
    let http: HttpTestingController;

    beforeEach(() => {
        localStorage.clear();
        vi.stubGlobal('ResizeObserver', ResizeObserverStub);
        TestBed.configureTestingModule({
            providers: [
                provideHttpClient(withInterceptors([activeOrgInterceptor])),
                provideHttpClientTesting(),
                { provide: ConfigService, useValue: { apiUrl: API_URL } as unknown as ConfigService },
            ],
        });
        http = TestBed.inject(HttpTestingController);
        TestBed.inject(ActiveOrgService).set(ORGANIZATION_A.id);
        TestBed.inject(ProfileService).getCurrentUser().subscribe();
        http.expectOne({ method: 'GET', url: PROFILE_URL }).flush({
            ...memberOf(ORGANIZATION_A, ORGANIZATION_B),
            custom_shortcuts: SAVED_SHORTCUTS,
        });
        fixture = TestBed.createComponent(ShortcutsSectionComponent);
        render();
    });

    afterEach(() => {
        http.verify();
        localStorage.clear();
        vi.unstubAllGlobals();
    });

    function render(): void {
        fixture.detectChanges();
        TestBed.tick();
    }

    async function settle(): Promise<void> {
        await fixture.whenStable();
        render();
    }

    function expectFlowsRequest(): TestRequest {
        return http.expectOne((request) => request.method === 'GET' && request.url === GRAPH_LIGHT_URL);
    }

    /** The resource hands the answer over a microtask later, so the list settles once the fixture is stable. */
    async function answerFlows(request: TestRequest, flows: { id: number; name: string }[]): Promise<void> {
        request.flush({
            count: flows.length,
            next: null,
            previous: null,
            results: flows.map((flow) => ({ ...flow, uuid: `uuid-${flow.id}`, description: '' })),
        });
        await settle();
    }

    function additionalLabels(): string[] {
        return Array.from(
            fixture.nativeElement.querySelectorAll('.shortcuts__row--custom .shortcuts__label') as NodeListOf<Element>,
            (label) => (label.textContent ?? '').trim()
        );
    }

    function headerButton(name: string): HTMLButtonElement | undefined {
        const header: HTMLElement = fixture.nativeElement.querySelector('.settings-section__header');
        return Array.from(header.querySelectorAll('button')).find(
            (button) => (button.textContent ?? '').trim() === name
        );
    }

    function newShortcutEditor(): Element | null {
        return fixture.nativeElement.querySelector('.shortcuts__flow > app-shortcut-editor');
    }

    it('opens the new-shortcut editor above the list from the header, and gives the focus back on Cancel', async () => {
        await answerFlows(expectFlowsRequest(), []);
        expect(newShortcutEditor()).toBeNull();

        headerButton('Add shortcut')!.click();
        render();

        const editor = newShortcutEditor()!;
        expect(editor).not.toBeNull();
        // Above the first group, where the user is looking, not after the list.
        expect(fixture.nativeElement.querySelector('.shortcuts__flow').firstElementChild).toBe(editor);

        const cancel = Array.from(editor.querySelectorAll('button')).find(
            (button) => (button.textContent ?? '').trim() === 'Cancel'
        )!;
        cancel.click();
        render();

        expect(newShortcutEditor()).toBeNull();
        expect(document.activeElement).toBe(headerButton('Add shortcut'));
    });

    it('resets every key to its default from the header, after the confirmation', async () => {
        await answerFlows(expectFlowsRequest(), []);

        headerButton('Reset to defaults')!.click();
        render();
        const dialog = document.querySelector('app-confirmation-dialog')!;
        expect((dialog.querySelector('.dialog-message')!.textContent ?? '').trim()).toBe(
            'Every node and flow action gets its own key back.'
        );
        Array.from(dialog.querySelectorAll('button'))
            .find((button) => (button.textContent ?? '').trim() === 'Reset')!
            .click();
        render();

        const patch = http.expectOne({ method: 'PATCH', url: PROFILE_URL });
        expect(patch.request.body).toEqual({
            custom_shortcuts: {
                custom: SAVED_SHORTCUTS.custom,
                overrides: {},
            },
        });
        patch.flush({
            ...memberOf(ORGANIZATION_A, ORGANIZATION_B),
            custom_shortcuts: patch.request.body.custom_shortcuts,
        });
        render();

        // Nothing differs from the defaults any more, so the header no longer offers the reset.
        expect(headerButton('Reset to defaults')).toBeUndefined();
        expect(headerButton('Add shortcut')).toBeDefined();
    });

    it("shortcuts section loads the active org's flows for subgraph labels", async () => {
        const request = expectFlowsRequest();
        expect(request.request.headers.get(ORGANIZATION_HEADER)).toBe(String(ORGANIZATION_A.id));

        await answerFlows(request, [
            { id: 12, name: 'Billing' },
            { id: 34, name: 'Support' },
        ]);

        // No flow is open here, so none of them is named "this flow".
        expect(additionalLabels()).toEqual(['Subgraph: Billing', 'Subgraph: Support']);
    });

    it('loads the flows again when the user switches organization', async () => {
        await answerFlows(expectFlowsRequest(), [
            { id: 12, name: 'Billing' },
            { id: 34, name: 'Support' },
        ]);

        TestBed.inject(ActiveOrgService).set(ORGANIZATION_B.id);
        await settle();
        const request = expectFlowsRequest();
        expect(request.request.headers.get(ORGANIZATION_HEADER)).toBe(String(ORGANIZATION_B.id));
        await answerFlows(request, [{ id: 34, name: 'Support in B' }]);

        expect(additionalLabels()).toEqual(['Subgraph: Flow not available', 'Subgraph: Support in B']);
    });

    it('still lists the shortcuts when the flows cannot be loaded', async () => {
        expectFlowsRequest().flush('Server error', { status: 500, statusText: 'Internal Server Error' });
        await settle();

        expect(additionalLabels()).toEqual(['Subgraph: Flow not available', 'Subgraph: Flow not available']);
    });
});
