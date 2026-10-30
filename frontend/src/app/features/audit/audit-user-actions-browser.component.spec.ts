import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { ActionCode, ResourceCode } from '@shared/models';
import { of } from 'rxjs';

import { PermissionsService } from '../../services/auth/permissions.service';
import { ConfigService } from '../../services/config';
import { AuditUserActionsBrowserComponent } from './audit-user-actions-browser.component';
import { AuditUserAction } from './models/audit-user-action.models';
import { AuditTokenService } from './services/audit-token.service';

const SEARCH_URL = '/auditor/api/audit/user_actions/search';
const PRESETS_URL = '/api/audit-filter-presets/';

const renamedFlow: AuditUserAction = {
    id: 'action-1',
    org_id: 1,
    event_time: '2026-10-30T10:00:00Z',
    record_time: null,
    filter_matched: true,
    actor_user_id: 3,
    actor_email: 'ann@example.com',
    actor_api_key_name: 'Deploy bot',
    action: 'renamed',
    target_type: 'flow',
    target_id: '4',
    target_name: 'Billing',
    previous_name: 'Invoices v2',
    parent_type: null,
    parent_id: null,
    parent_name: null,
    route: null,
};

function setup(canExport = true) {
    TestBed.configureTestingModule({
        providers: [
            provideHttpClient(),
            provideHttpClientTesting(),
            { provide: ConfigService, useValue: { apiUrl: '/api/', auditorUrl: '/auditor/' } },
            { provide: AuditTokenService, useValue: { getToken: () => of('audit-token') } },
            {
                provide: PermissionsService,
                useValue: {
                    can: (resource: ResourceCode, action: ActionCode) =>
                        canExport || !(resource === ResourceCode.UserAudit && action === ActionCode.Export),
                },
            },
        ],
    });
    const fixture = TestBed.createComponent(AuditUserActionsBrowserComponent);
    const http = TestBed.inject(HttpTestingController);
    fixture.detectChanges();
    return { fixture, http, root: fixture.nativeElement as HTMLElement };
}

function flushSearch(http: HttpTestingController, items: AuditUserAction[]): Record<string, unknown> {
    const request = http.expectOne(SEARCH_URL);
    request.flush({ items, next_cursor: null, partial: false });
    return request.request.body;
}

function buttonWithText(root: HTMLElement, text: string): HTMLButtonElement {
    const button = Array.from(root.querySelectorAll('button')).find((item) => item.textContent?.trim() === text);
    if (button === undefined) {
        throw new Error(`No "${text}" button`);
    }
    return button;
}

async function render(fixture: ComponentFixture<AuditUserActionsBrowserComponent>): Promise<void> {
    fixture.detectChanges();
    await fixture.whenStable();
}

describe('AuditUserActionsBrowserComponent', () => {
    it('shows when, who and what for each action', async () => {
        const { fixture, http, root } = setup();
        flushSearch(http, [renamedFlow]);
        await render(fixture);

        const headers = Array.from(root.querySelectorAll('th')).map((cell) => cell.textContent?.trim());
        const cells = Array.from(root.querySelectorAll('tbody tr td')).map((cell) =>
            cell.textContent?.replace(/\s+/g, ' ').trim()
        );
        expect(headers).toEqual(['When', 'Who', 'What']);
        expect(cells.slice(1)).toEqual([
            'ann@example.com via API key Deploy bot',
            'renamed flow "Invoices v2" → "Billing"',
        ]);
    });

    it('searches user actions with the typed text and no match scope', async () => {
        const { fixture, http, root } = setup();
        flushSearch(http, []);
        await render(fixture);

        const search = root.querySelector<HTMLInputElement>('input[aria-label="Search every field"]')!;
        search.value = 'ann';
        search.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter' }));

        expect(flushSearch(http, [])).toEqual({
            filters: { field: '__text__', op: 'contains', value: 'ann' },
            cursor: null,
            size: 20,
        });
    });

    it('lists and saves presets in the user actions domain', async () => {
        const { fixture, http, root } = setup();
        flushSearch(http, []);
        await render(fixture);

        buttonWithText(root, 'Filters').click();
        await render(fixture);
        const list = http.expectOne((request) => request.url === PRESETS_URL && request.method === 'GET');
        expect(list.request.params.get('domain')).toBe('user_actions');
        list.flush({ count: 0, next: null, previous: null, results: [] });
        await render(fixture);

        buttonWithText(root, 'New Preset').click();
        await render(fixture);
        const name = root.querySelector<HTMLInputElement>('#audit-preset-name')!;
        name.value = 'Deletes';
        name.dispatchEvent(new Event('input'));
        await render(fixture);
        buttonWithText(root, 'Save Changes').click();

        const save = http.expectOne((request) => request.url === PRESETS_URL && request.method === 'POST');
        expect(save.request.params.get('domain')).toBe('user_actions');
        expect(save.request.body.name).toBe('Deletes');
        expect(save.request.body.filter_body.match_scope).toBeUndefined();
    });

    it.each([
        [true, 1],
        [false, 0],
    ])('shows export only with the user audit export permission (%s)', async (canExport, exportButtons) => {
        const { fixture, http, root } = setup(canExport);
        flushSearch(http, [renamedFlow]);
        await render(fixture);

        expect(root.querySelectorAll('app-action-dropdown-button')).toHaveLength(exportButtons);
    });
});
