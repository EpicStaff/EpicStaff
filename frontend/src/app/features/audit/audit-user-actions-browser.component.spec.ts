import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { ActionCode, ResourceCode } from '@shared/models';
import { of } from 'rxjs';

import { ActiveOrgService } from '../../services/auth/active-org.service';
import { PermissionsService } from '../../services/auth/permissions.service';
import { ConfigService } from '../../services/config';
import { AuditUserActionsBrowserComponent } from './audit-user-actions-browser.component';
import { AuditUserAction } from './models/audit-user-action.models';
import { AuditTokenService } from './services/audit-token.service';

const SEARCH_URL = '/auditor/api/audit/user_actions/search';
const PRESETS_URL = '/api/audit-filter-presets/';
const FLOWS_URL = '/api/graph-light/';
const MEMBERS_URL = '/api/admin/memberships/';
const TARGET_TYPES_URL = '/auditor/api/audit/user_actions/values/target_type';

const renamedFlow: AuditUserAction = {
    id: 'action-1',
    org_id: 1,
    event_time: '2026-10-30T10:00:00Z',
    record_time: null,
    filter_matched: true,
    number: 41,
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
    number: 42,
    actor_api_key_name: null,
    action: 'import_entity',
    target_type: 'python code node',
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
    number: 43,
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
    number: 44,
    action: 'updated',
    parent_type: 'flow',
    parent_id: '4',
    parent_name: 'Billing',
};

const deletedTool: AuditUserAction = {
    ...signIn,
    id: 'action-5',
    number: 45,
    action: 'moved_to_recycle_bin',
    target_type: 'tool',
    target_id: '9',
    parent_type: 'agent',
    parent_id: '7',
    parent_name: 'Researcher',
};

const typeOnlyParent: AuditUserAction = {
    ...signIn,
    id: 'action-6',
    // stored before records were numbered
    number: null,
    action: 'updated',
    parent_type: 'flow',
};

function setup(canExport = true, deniedResources: ResourceCode[] = []) {
    TestBed.configureTestingModule({
        providers: [
            provideHttpClient(),
            provideHttpClientTesting(),
            { provide: ConfigService, useValue: { apiUrl: '/api/', auditorUrl: '/auditor/' } },
            { provide: AuditTokenService, useValue: { getToken: () => of('audit-token') } },
            { provide: ActiveOrgService, useValue: { activeOrgId: () => 1 } },
            {
                provide: PermissionsService,
                useValue: {
                    can: (resource: ResourceCode, action: ActionCode) =>
                        !deniedResources.includes(resource) &&
                        (canExport || !(resource === ResourceCode.UserAudit && action === ActionCode.Export)),
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

function cellText(element: Element): string | undefined {
    return element.textContent?.replace(/\s+/g, ' ').trim();
}

async function render(fixture: ComponentFixture<AuditUserActionsBrowserComponent>): Promise<void> {
    fixture.detectChanges();
    await fixture.whenStable();
}

function page<T>(results: T[]) {
    return { count: results.length, next: null, previous: null, results };
}

function flushLookups(http: HttpTestingController): void {
    http.expectOne((request) => request.url === FLOWS_URL).flush(
        page([
            { id: 15, name: 'Onboarding' },
            { id: 12, name: 'Billing' },
        ])
    );
    http.expectOne((request) => request.url === MEMBERS_URL).flush(
        page([
            { user: { id: 4, email: 'bob@example.com', display_name: null } },
            { user: { id: 3, email: 'ann@example.com', display_name: 'Ann Lee' } },
        ])
    );
}

async function openFilters(fixture: ComponentFixture<AuditUserActionsBrowserComponent>, http: HttpTestingController) {
    const root: HTMLElement = fixture.nativeElement;
    buttonWithText(root, 'Filters').click();
    await render(fixture);
    http.expectOne((request) => request.url === PRESETS_URL).flush(page([]));
    buttonWithText(root, 'Builder').click();
    await render(fixture);
}

function filterGroup(root: HTMLElement, label: string): HTMLElement {
    const group = Array.from(root.querySelectorAll<HTMLElement>('app-audit-filter-group')).find(
        (item) => item.querySelector('.filter-group__title')?.textContent?.trim() === label
    );
    if (group === undefined) {
        throw new Error(`No "${label}" filter`);
    }
    return group;
}

function optionLabels(group: HTMLElement): (string | undefined)[] {
    return Array.from(group.querySelectorAll('.checkbox-enum__option span')).map((item) => cellText(item));
}

// The filter controls measure themselves with ResizeObserver, which jsdom lacks.
class ResizeObserverStub {
    observe(): void {}
    unobserve(): void {}
    disconnect(): void {}
}

beforeEach(() => vi.stubGlobal('ResizeObserver', ResizeObserverStub));
afterEach(() => vi.unstubAllGlobals());

describe('AuditUserActionsBrowserComponent', () => {
    it('shows id, date, user, action, target type, target name and target parent for each action', async () => {
        const { fixture, http, root } = setup();
        flushSearch(http, [renamedFlow, editedNode, signIn, parentOnly, deletedTool, typeOnlyParent]);
        await render(fixture);

        const headers = Array.from(root.querySelectorAll('th')).map((cell) => cell.textContent?.trim());
        // the date cell is left out: its text depends on the time zone the test runs in
        const rows = Array.from(root.querySelectorAll('tbody tr')).map((row) =>
            Array.from(row.querySelectorAll('td'))
                .filter((_cell, index) => index !== 1)
                .map((cell) => cellText(cell))
        );
        expect(headers).toEqual(['ID', 'Date', 'User', 'Action', 'Target Type', 'Target Name', 'Target Parent']);
        expect(rows).toEqual([
            ['41', 'ann@example.com via API key Deploy bot', 'Renamed', 'Flow', 'Invoices v2 → Billing', ''],
            ['42', 'ann@example.com', 'Import entity', 'Python code node', 'Parse invoice', 'Billing · Flow'],
            ['43', 'ann@example.com', 'Sign-in failed', '', '', ''],
            ['44', 'ann@example.com', 'Updated', '', '', 'Billing · Flow'],
            ['45', 'ann@example.com', 'Moved to Recycle Bin', 'Tool', '#9', 'Researcher · Agent'],
            // a record stored before records were numbered has a blank ID
            ['', 'ann@example.com', 'Updated', '', '', 'Flow'],
        ]);
    });

    it('colours each action by its tone, the way Sessions colours statuses', async () => {
        const { fixture, http, root } = setup();
        flushSearch(http, [renamedFlow, editedNode, signIn, deletedTool]);
        await render(fixture);

        const tones = Array.from(root.querySelectorAll('.audit-action')).map((action) =>
            Array.from(action.classList).find((name) => name.startsWith('audit-action--'))
        );
        expect(tones).toEqual([
            'audit-action--changed',
            'audit-action--plain',
            'audit-action--destroyed',
            'audit-action--removed',
        ]);
    });

    it('highlights the searched text in target and parent names, not in the parent type', async () => {
        const { fixture, http, root } = setup();
        flushSearch(http, []);
        await render(fixture);

        const search = root.querySelector<HTMLInputElement>('input[aria-label="Search every field"]')!;
        search.value = 'bill';
        search.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter' }));
        flushSearch(http, [renamedFlow, editedNode]);
        await render(fixture);

        const marks = Array.from(root.querySelectorAll('tbody tr')).map((row) =>
            Array.from(row.querySelectorAll('td')).map((cell) =>
                Array.from(cell.querySelectorAll('mark')).map((mark) => mark.textContent)
            )
        );
        expect(marks).toEqual([
            [[], [], [], [], [], ['Bill'], []],
            [[], [], [], [], [], [], ['Bill']],
        ]);
    });

    it('widens a column by the distance its header edge is dragged', async () => {
        const { fixture, http, root } = setup();
        flushSearch(http, [editedNode]);
        await render(fixture);

        const idHeader = root.querySelector('th')!;
        // the test DOM has no layout or pointer capture, so the header reports its on-screen width here
        vi.spyOn(idHeader, 'getBoundingClientRect').mockReturnValue(new DOMRect(0, 0, 100, 30));
        const handle = idHeader.querySelector<HTMLElement>('.audit-table__resize-handle')!;
        handle.setPointerCapture = () => undefined;
        handle.dispatchEvent(new MouseEvent('pointerdown', { button: 0, clientX: 100 }));
        handle.dispatchEvent(new MouseEvent('pointermove', { clientX: 130 }));
        handle.dispatchEvent(new Event('lostpointercapture'));
        handle.dispatchEvent(new MouseEvent('pointermove', { clientX: 200 }));
        await render(fixture);

        expect(root.querySelector<HTMLElement>('col')!.style.width).toBe('130px');
    });

    // per row: each link's visible text, its label and where it opens, in a new tab
    function rowLinks(root: HTMLElement): string[][] {
        return Array.from(root.querySelectorAll('tbody tr')).map((row) =>
            Array.from(row.querySelectorAll<HTMLAnchorElement>('a[target="_blank"]')).map(
                (link) => `${cellText(link)} | ${link.getAttribute('aria-label')} -> ${link.getAttribute('href')}`
            )
        );
    }

    it('opens the target and its parent in a new tab, but not a deleted target', async () => {
        const { fixture, http, root } = setup();
        flushSearch(http, [editedNode, { ...editedNode, id: 'action-7', number: 46, action: 'deleted' }]);
        await render(fixture);

        expect(rowLinks(root)).toEqual([
            [
                'Parse invoice | Open python code node Parse invoice (opens in a new tab) -> /flows/4?nodeId=12',
                'Billing · Flow | Open flow Billing (opens in a new tab) -> /flows/4',
            ],
            ['Billing · Flow | Open flow Billing (opens in a new tab) -> /flows/4'],
        ]);
    });

    it('opens a target moved to the recycle bin in its recycle-bin tab, searched to it', async () => {
        const { fixture, http, root } = setup();
        flushSearch(http, [{ ...renamedFlow, action: 'moved_to_recycle_bin', previous_name: null }]);
        await render(fixture);

        expect(rowLinks(root)).toEqual([
            [
                'Billing | Open flow Billing in the recycle bin (opens in a new tab) -> /recycle-bin/flows?search=Billing',
            ],
        ]);
    });

    it('names a renamed target by its new name', async () => {
        const { fixture, http, root } = setup();
        flushSearch(http, [renamedFlow]);
        await render(fixture);

        expect(rowLinks(root)).toEqual([
            ['Invoices v2 → Billing | Open flow Billing (opens in a new tab) -> /flows/4'],
        ]);
    });

    it('offers no link to a page the viewer may not open', async () => {
        const { fixture, http, root } = setup(true, [ResourceCode.Flows]);
        flushSearch(http, [editedNode]);
        await render(fixture);

        expect(rowLinks(root)).toEqual([[]]);
    });

    it('opens no value viewer or side panel when a row is clicked', async () => {
        const { fixture, http, root } = setup();
        flushSearch(http, [editedNode]);
        await render(fixture);

        const row = root.querySelector('tbody tr')!;
        expect(row.querySelector('button')).toBeNull();
        (row.querySelector('td:last-child') as HTMLElement).click();
        await render(fixture);
        expect(root.querySelector('app-audit-value-viewer')).toBeNull();
        expect(root.querySelector('aside')).toBeNull();
    });

    it('offers the active org members and its flows, by name', async () => {
        const { fixture, http, root } = setup();
        flushSearch(http, []);
        const members = http.expectOne((request) => request.url === MEMBERS_URL);
        expect(members.request.params.get('org_ids')).toBe('1');
        expect(members.request.params.get('page_size')).toBe('200');
        members.flush(
            page([
                { user: { id: 4, email: 'bob@example.com', display_name: null } },
                { user: { id: 3, email: 'ann@example.com', display_name: 'Ann Lee' } },
            ])
        );
        http.expectOne((request) => request.url === FLOWS_URL).flush(page([{ id: 12, name: 'Billing' }]));
        await openFilters(fixture, http);

        expect(optionLabels(filterGroup(root, 'User'))).toEqual(['Ann Lee (ann@example.com)', 'bob@example.com']);
        expect(optionLabels(filterGroup(root, 'Flow'))).toEqual(['Billing']);
    });

    it('leaves the Flow, User and Target Type lists empty when they fail to load', async () => {
        const { fixture, http, root } = setup();
        flushSearch(http, []);
        http.expectOne((request) => request.url === FLOWS_URL).flush(null, { status: 500, statusText: 'Error' });
        http.expectOne((request) => request.url === MEMBERS_URL).flush(null, { status: 403, statusText: 'Forbidden' });
        http.expectOne(TARGET_TYPES_URL).flush(null, { status: 500, statusText: 'Error' });
        await openFilters(fixture, http);

        expect(optionLabels(filterGroup(root, 'User'))).toEqual([]);
        expect(optionLabels(filterGroup(root, 'Flow'))).toEqual([]);
        expect(optionLabels(filterGroup(root, 'Target Type'))).toEqual([]);
    });

    it('offers the recorded target types capitalized, and searches the picked one by its raw value', async () => {
        const { fixture, http, root } = setup();
        flushSearch(http, []);
        flushLookups(http);
        const targetTypes = http.expectOne(TARGET_TYPES_URL);
        expect(targetTypes.request.headers.get('Authorization')).toBe('Bearer audit-token');
        targetTypes.flush({ field: 'target_type', values: ['agent', 'python node'] });
        await openFilters(fixture, http);

        const targetType = filterGroup(root, 'Target Type');
        expect(optionLabels(targetType)).toEqual(['Agent', 'Python node']);
        targetType.querySelectorAll<HTMLInputElement>('.checkbox-enum__option input')[1].click();
        await render(fixture);
        buttonWithText(root, 'Apply Filters').click();
        await render(fixture);

        expect(flushSearch(http, [])['filters']).toEqual({ field: 'target_type', op: 'in', value: ['python node'] });
        await render(fixture);
        const chips = Array.from(root.querySelectorAll('.filter-chip')).map((chip) => [
            cellText(chip.querySelector('.filter-chip__label')!),
            cellText(chip.querySelector('.filter-chip__value')!),
        ]);
        expect(chips).toEqual([['Target Type', 'is any of Python node']]);
    });

    it('searches the picked flow by id and shows its name in the applied chip', async () => {
        const { fixture, http, root } = setup();
        flushSearch(http, []);
        flushLookups(http);
        await openFilters(fixture, http);

        filterGroup(root, 'Flow').querySelector<HTMLInputElement>('.checkbox-enum__option input')!.click();
        await render(fixture);
        buttonWithText(root, 'Apply Filters').click();
        await render(fixture);

        expect(flushSearch(http, [])['filters']).toEqual({
            op: 'or',
            children: [
                {
                    op: 'and',
                    children: [
                        { field: 'target_type', op: 'equals', value: 'flow' },
                        { field: 'target_id', op: 'in', value: ['12'] },
                    ],
                },
                {
                    op: 'and',
                    children: [
                        { field: 'parent_type', op: 'equals', value: 'flow' },
                        { field: 'parent_id', op: 'in', value: ['12'] },
                    ],
                },
            ],
        });
        await render(fixture);
        const chips = Array.from(root.querySelectorAll('.filter-chip')).map((chip) => [
            cellText(chip.querySelector('.filter-chip__label')!),
            cellText(chip.querySelector('.filter-chip__value')!),
        ]);
        expect(chips).toEqual([['Flow', 'is any of Billing']]);
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
