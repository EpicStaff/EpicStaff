import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { CUSTOM_ELEMENTS_SCHEMA } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { FormsModule } from '@angular/forms';
import { JsonEditorComponent } from '@shared/components';
import { ActionCode, ResourceCode } from '@shared/models';
import { MonacoEditorModule } from 'ngx-monaco-editor-v2';
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

const editedNode: AuditUserAction = {
    ...renamedFlow,
    id: 'action-2',
    actor_api_key_name: null,
    action: 'import_entity',
    target_type: 'python node',
    target_id: '12',
    target_name: 'Parse invoice',
    previous_name: null,
    parent_type: 'flow',
    parent_id: '4',
    parent_name: 'Billing',
};

const signIn: AuditUserAction = {
    ...renamedFlow,
    id: 'action-3',
    actor_api_key_name: null,
    action: 'sign_in_failed',
    target_type: null,
    target_id: null,
    target_name: null,
    previous_name: null,
};

const parentOnly: AuditUserAction = {
    ...signIn,
    id: 'action-4',
    action: 'updated',
    parent_type: 'flow',
    parent_id: '4',
    parent_name: 'Billing',
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
    // Monaco does not run in jsdom: render the value viewer's editor as an unknown custom element instead.
    TestBed.overrideComponent(JsonEditorComponent, {
        remove: { imports: [MonacoEditorModule, FormsModule] },
        add: { schemas: [CUSTOM_ELEMENTS_SCHEMA] },
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

function cellText(element: Element): string | undefined {
    return element.textContent?.replace(/\s+/g, ' ').trim();
}

// the text a screen reader reads: the content minus anything hidden from it
function spokenText(element: Element): string | undefined {
    const copy = element.cloneNode(true) as Element;
    copy.querySelectorAll('[aria-hidden="true"]').forEach((hidden) => hidden.remove());
    return cellText(copy);
}

async function render(fixture: ComponentFixture<AuditUserActionsBrowserComponent>): Promise<void> {
    fixture.detectChanges();
    await fixture.whenStable();
}

describe('AuditUserActionsBrowserComponent', () => {
    it('shows date, user, action and target for each action', async () => {
        const { fixture, http, root } = setup();
        flushSearch(http, [renamedFlow, editedNode, signIn, parentOnly]);
        await render(fixture);

        const headers = Array.from(root.querySelectorAll('th')).map((cell) => cell.textContent?.trim());
        const rows = Array.from(root.querySelectorAll('tbody tr')).map((row) => {
            const [, user, action, target] = Array.from(row.querySelectorAll('td'));
            return [cellText(user), cellText(action), spokenText(target)];
        });
        expect(headers).toEqual(['Date', 'User', 'Action', 'Target']);
        // the target and parent lines are separate blocks, so the spoken text must keep them apart
        expect(rows).toEqual([
            ['ann@example.com via API key Deploy bot', 'Renamed', 'flow "Invoices v2" → "Billing"'],
            ['ann@example.com', 'Import entity', 'python node "Parse invoice", in flow "Billing"'],
            ['ann@example.com', 'Sign-in failed', 'No target'],
            ['ann@example.com', 'Updated', 'No target, in flow "Billing"'],
        ]);
        expect(cellText(root.querySelectorAll('tbody tr')[2].querySelector('td:last-child button')!)).toBe(
            '—No target'
        );
    });

    it.each([
        [0, 'User action - Import entity python node "Parse invoice"'],
        [1, 'User action - Sign-in failed'],
    ])('opens row %i from its target cell', async (rowIndex, title) => {
        const { fixture, http, root } = setup();
        flushSearch(http, [editedNode, signIn]);
        await render(fixture);

        const targets = Array.from(root.querySelectorAll<HTMLButtonElement>('tbody tr td:last-child button'));
        targets[rowIndex].click();
        await render(fixture);

        expect(targets.map((button) => button.getAttribute('aria-expanded'))).toEqual(
            targets.map((_button, index) => String(index === rowIndex))
        );
        expect(root.querySelector('app-audit-value-viewer')?.textContent).toContain(title);
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

    it('exports the filtered actions as a user actions job, without a match scope', async () => {
        const downloads: string[] = [];
        vi.spyOn(URL, 'createObjectURL').mockReturnValue('blob:export');
        vi.spyOn(URL, 'revokeObjectURL').mockReturnValue(undefined);
        vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(function (this: HTMLAnchorElement) {
            downloads.push(this.download);
        });
        const { fixture, http, root } = setup();
        flushSearch(http, [renamedFlow]);
        await render(fixture);

        root.querySelector<HTMLButtonElement>('app-action-dropdown-button .adb__main')!.click();
        const start = http.expectOne('/auditor/api/audit/user_actions/export');
        expect(start.request.method).toBe('POST');
        expect(start.request.body).toEqual({ format: 'json' });
        start.flush({ job_id: 'job-7' });
        // the first poll fires on timer(0); whenStable would wait for the whole polling interval
        await new Promise((resolve) => setTimeout(resolve));
        http.expectOne('/auditor/api/audit/user_actions/export/job-7').flush(new Blob(['[]']));

        expect(downloads).toHaveLength(1);
        expect(downloads[0]).toMatch(/^audit_user_actions_export_\d+\.json$/);
    });
});
