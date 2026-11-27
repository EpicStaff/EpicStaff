import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { FlowEditorPreferences, GetMeResponse } from '@shared/models';

import { ProfileService } from '../../../../../../../services/auth/profile.service';
import {
    API_URL,
    memberOf,
    ORGANIZATION_A,
    PROFILE_URL,
} from '../../../../../../../services/auth/testing/current-user-fixtures';
import { PREFERENCES_SAVE_DEBOUNCE_MS } from '../../../../../../../services/auth/user-preferences.service';
import { ConfigService } from '../../../../../../../services/config';
import { FlowEditorSectionComponent } from './flow-editor-section.component';

const FLOW_EDITOR_URL = '/api/profile/preferences/flow_editor/';

describe('FlowEditorSectionComponent', () => {
    let fixture: ComponentFixture<FlowEditorSectionComponent>;
    let http: HttpTestingController;

    beforeEach(() => {
        localStorage.clear();
        // Only the save debounce: the default fakes would also replace Date and Intl.
        vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] });
        TestBed.configureTestingModule({
            providers: [
                provideHttpClient(),
                provideHttpClientTesting(),
                { provide: ConfigService, useValue: { apiUrl: API_URL } as unknown as ConfigService },
            ],
        });
        http = TestBed.inject(HttpTestingController);
    });

    afterEach(() => {
        http.verify();
        vi.useRealTimers();
    });

    function render(flowEditor: Partial<FlowEditorPreferences> = {}): void {
        const user: GetMeResponse = memberOf(ORGANIZATION_A);
        TestBed.inject(ProfileService).getCurrentUser().subscribe();
        http.expectOne({ method: 'GET', url: PROFILE_URL }).flush({
            ...user,
            preferences: { ...user.preferences, flow_editor: { ...user.preferences.flow_editor, ...flowEditor } },
        });
        fixture = TestBed.createComponent(FlowEditorSectionComponent);
        fixture.detectChanges();
    }

    function toggle(label: string): HTMLInputElement {
        return fixture.nativeElement.querySelector(`input[type="checkbox"][aria-label="${label}"]`);
    }

    function onOpenOption(label: string): HTMLButtonElement {
        return [...fixture.nativeElement.querySelectorAll('app-radio-button button')].find(
            (button: HTMLButtonElement) => button.textContent?.trim() === label
        );
    }

    function savedChange(): unknown {
        vi.advanceTimersByTime(PREFERENCES_SAVE_DEBOUNCE_MS);
        const save = http.expectOne({ method: 'PATCH', url: FLOW_EDITOR_URL });
        save.flush({});
        return save.request.body;
    }

    it("shows the account's values", () => {
        render({ show_minimap: false, edge_style: 'adaptive-curve', on_open: 'restore' });

        expect(toggle('Show minimap').checked).toBe(false);
        expect(toggle('Curved connections').checked).toBe(true);
        expect(toggle('Arrow colors').checked).toBe(true);
        expect(onOpenOption('Restore where I left it').getAttribute('aria-pressed')).toBe('true');
    });

    it.each([
        ['Show minimap', { show_minimap: false }],
        ['Arrow colors', { arrow_colors: false }],
        ['Curved connections', { edge_style: 'adaptive-curve' }],
        ['Highlight unused nodes', { highlight_unused_nodes: true }],
    ])('saves "%s" to the account', (label, expected) => {
        render();

        toggle(label).click();

        expect(savedChange()).toEqual(expected);
    });

    it('names the on-open choice group by its label', () => {
        render();

        const element = fixture.nativeElement as HTMLElement;
        const groups = Array.from(element.querySelectorAll('[role="group"]'));
        expect(groups).toHaveLength(1);
        const labelId = groups[0].getAttribute('aria-labelledby')!;
        expect(element.querySelector(`#${labelId}`)?.textContent?.trim()).toBe('When a flow opens');
    });

    it('saves what happens when a flow opens', () => {
        render();

        onOpenOption('Restore where I left it').click();

        expect(savedChange()).toEqual({ on_open: 'restore' });
    });
});
