import { HttpErrorResponse, provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { provideRouter, Router } from '@angular/router';
import { RouterTestingHarness } from '@angular/router/testing';
import { AuthorshipDetailsDialogService } from '@shared/components';
import { GetMcpToolRequest } from '@shared/models';
import { NEVER, of, throwError } from 'rxjs';

import { ConfigService } from '../../../../../../services/config';
import { ToastService } from '../../../../../../services/notifications';
import { storedZip } from '../../../../../../shared/utils/read-export-envelope.testing';
import { ToolsViewStorageService } from '../../../../services/tools-view-storage.service';
import { ToolCardVM } from '../tool-card/tool-card.model';
import { McpToolsPort } from './mcp-tools.port';
import { ToolsListComponent } from './tools-list.component';
import { TOOLS_LIST_PORT } from './tools-list-port';

// jsdom has no ResizeObserver; the overflow tooltips only need it to exist.
class ResizeObserverStub {
    observe(): void {}
    unobserve(): void {}
    disconnect(): void {}
}

beforeEach(() => vi.stubGlobal('ResizeObserver', ResizeObserverStub));

const MCP_TOOL: GetMcpToolRequest = {
    id: 9,
    name: 'Weather MCP',
    labels: [],
    transport: 'https://mcp.example/sse',
    tool_name: 'weather',
    org: 1,
    is_favorite: false,
    created_at: '2026-03-12T13:28:23Z',
    updated_at: '2026-03-13T09:00:00Z',
    created_by: { id: 1, display_name: 'Ivan Bohun', avatar_url: null },
    last_edited_by: null,
    last_edited_at: null,
};

const MCP_CARD: ToolCardVM = {
    id: MCP_TOOL.id,
    kind: 'mcp',
    name: MCP_TOOL.name,
    description: '',
    labelIds: [],
    favorite: false,
    builtIn: false,
};

describe('ToolsListComponent "view_details" action', () => {
    it('opens "Tool Details" with the authorship of the chosen tool, closing back to the card menu trigger', () => {
        const authorshipDetailsDialog = { open: vi.fn() };
        const port = {
            kind: 'mcp',
            entityLabel: 'MCP tool',
            entityLabelPlural: 'MCP tools',
            filterAdapter: {
                idOf: (tool: GetMcpToolRequest) => tool.id,
                nameOf: (tool: GetMcpToolRequest) => tool.name,
                labelIdsOf: (tool: GetMcpToolRequest) => tool.labels,
                favoriteOf: (tool: GetMcpToolRequest) => tool.is_favorite,
                searchableTextOf: (tool: GetMcpToolRequest) => [tool.name],
                updatedAtOf: (tool: GetMcpToolRequest) => tool.updated_at,
            },
            createdEvent$: NEVER,
            isBuiltIn: () => false,
            descriptionOf: () => '',
            getAll: () => of([MCP_TOOL]),
            getBulkUsage: () => of([]),
        };
        TestBed.configureTestingModule({
            providers: [
                provideHttpClient(),
                provideHttpClientTesting(),
                provideRouter([]),
                { provide: TOOLS_LIST_PORT, useValue: port },
                { provide: AuthorshipDetailsDialogService, useValue: authorshipDetailsDialog },
            ],
        });
        const fixture = TestBed.createComponent(ToolsListComponent);
        fixture.detectChanges();

        const trigger = document.createElement('button');

        fixture.componentInstance.onCardMenuAction({ tool: MCP_CARD, action: 'view_details', trigger });

        expect(authorshipDetailsDialog.open).toHaveBeenCalledWith('Tool Details', MCP_TOOL, trigger);
    });
});

describe('ToolsListComponent export and import', () => {
    const TOOLS_URL = '/api/mcp-tools/';
    const EXPORT_JOBS_URL = '/api/mcp-tools/export-jobs/';
    const JOB_URL = '/api/transfer-jobs/job-1/';
    const ENVELOPE = { main_entity: 'MCPTool', version: 6 };

    let httpMock: HttpTestingController;
    let component: ToolsListComponent;
    let downloads: string[];

    beforeEach(() => {
        downloads = [];
        vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(function (this: HTMLAnchorElement) {
            downloads.push(this.href);
        });
        TestBed.configureTestingModule({
            providers: [
                provideHttpClient(),
                provideHttpClientTesting(),
                provideRouter([]),
                { provide: ConfigService, useValue: { apiUrl: '/api/' } },
                { provide: TOOLS_LIST_PORT, useClass: McpToolsPort },
            ],
        });
        httpMock = TestBed.inject(HttpTestingController);
        const fixture = TestBed.createComponent(ToolsListComponent);
        component = fixture.componentInstance;
        fixture.detectChanges();
        answerToolList();
    });

    afterEach(() => vi.restoreAllMocks());

    function answerToolList(): void {
        httpMock
            .match((request) => request.url === TOOLS_URL && request.method === 'GET')
            .forEach((request) => request.flush({ count: 1, next: null, previous: null, results: [MCP_TOOL] }));
    }

    async function finishExportJob(): Promise<void> {
        (await vi.waitFor(() => httpMock.expectOne(JOB_URL))).flush({
            id: 'job-1',
            kind: 'export',
            main_entity: 'MCPTool',
            status: 'completed',
            display_name: 'Weather MCP',
            file_name: 'Weather MCP.zip',
            result: { excluded: [] },
            error: null,
            created_at: '2026-11-06T10:00:00Z',
            finished_at: '2026-11-06T10:01:00Z',
            expires_at: null,
        });
        httpMock
            .expectOne('/api/transfer-jobs/job-1/download-ticket/')
            .flush({ download_url: '/api/transfer-jobs/job-1/download/?ticket=t-1' });
    }

    it('exports a tool from its card as a background job and downloads the archive once ready', async () => {
        component.onCardMenuAction({ tool: MCP_CARD, action: 'export', trigger: document.createElement('button') });

        const start = httpMock.expectOne(EXPORT_JOBS_URL);
        expect(start.request.body).toEqual({ ids: [9] });
        start.flush({ job_id: 'job-1' }, { status: 202, statusText: 'Accepted' });
        await finishExportJob();

        expect(downloads).toEqual([expect.stringContaining('/api/transfer-jobs/job-1/download/?ticket=t-1')]);
    });

    it('exports the selected tools in one job', () => {
        component.handleBulkExport([9, 10]);

        expect(httpMock.expectOne(EXPORT_JOBS_URL).request.body).toEqual({ ids: [9, 10] });
    });

    it('loads the tools again when a tool to export is gone', () => {
        component.onCardMenuAction({ tool: MCP_CARD, action: 'export', trigger: document.createElement('button') });

        httpMock.expectOne(EXPORT_JOBS_URL).flush({ message: 'Not found.' }, { status: 404, statusText: 'Not Found' });

        httpMock.expectOne((request) => request.url === TOOLS_URL && request.method === 'GET');
    });

    it('imports a .zip export: inspects only its envelope and uploads the archive itself', async () => {
        const archive = storedZip('tools.zip', { 'export.json': JSON.stringify(ENVELOPE) });
        const picker = document.createElement('input');
        vi.spyOn(picker, 'click').mockImplementation(() => undefined);
        const createElement = vi.spyOn(document, 'createElement').mockReturnValueOnce(picker);
        TestBed.inject(ToolsViewStorageService).dispatch({ kind: 'open-import' });
        createElement.mockRestore();
        expect(picker.accept).toBe('.json,.zip');
        Object.defineProperty(picker, 'files', { value: [archive] });
        picker.dispatchEvent(new Event('change'));

        const inspect = await vi.waitFor(() => httpMock.expectOne('/api/mcp-tools/import/inspect/'));
        const inspected = (inspect.request.body as FormData).get('file') as File;
        expect(JSON.parse(await inspected.text())).toEqual(ENVELOPE);
        inspect.flush({ review_items: [] });

        const upload = httpMock.expectOne('/api/mcp-tools/import/');
        expect((upload.request.body as FormData).get('file')).toBe(archive);
    });
});

describe('ToolsListComponent "duplicate" action', () => {
    it('shows the reason the backend gives for refusing a copy', () => {
        const reason = 'This contains code that reads secrets. This action requires the Use permission on secrets.';
        const toast = { error: vi.fn(), success: vi.fn() };
        const port = {
            kind: 'mcp',
            entityLabelPlural: 'MCP tools',
            filterAdapter: {
                idOf: (tool: GetMcpToolRequest) => tool.id,
                nameOf: (tool: GetMcpToolRequest) => tool.name,
                labelIdsOf: (tool: GetMcpToolRequest) => tool.labels,
                favoriteOf: (tool: GetMcpToolRequest) => tool.is_favorite,
                searchableTextOf: (tool: GetMcpToolRequest) => [tool.name],
                updatedAtOf: (tool: GetMcpToolRequest) => tool.updated_at,
            },
            createdEvent$: NEVER,
            isBuiltIn: () => false,
            descriptionOf: () => '',
            getAll: () => of([MCP_TOOL]),
            getBulkUsage: () => of([]),
            copy: () =>
                throwError(
                    () =>
                        new HttpErrorResponse({
                            status: 403,
                            error: {
                                status_code: 403,
                                code: 'code_with_secrets_requires_secrets_use_permission',
                                message: reason,
                            },
                        })
                ),
        };
        TestBed.configureTestingModule({
            providers: [
                provideHttpClient(),
                provideHttpClientTesting(),
                provideRouter([]),
                { provide: TOOLS_LIST_PORT, useValue: port },
                { provide: ToastService, useValue: toast },
            ],
        });
        const fixture = TestBed.createComponent(ToolsListComponent);
        fixture.detectChanges();

        fixture.componentInstance.onCardMenuAction({ tool: MCP_CARD, action: 'duplicate' });

        expect(toast.error).toHaveBeenCalledExactlyOnceWith(reason);
    });
});

describe('ToolsListComponent bulk duplicate', () => {
    it('duplicates only the selected tools this user may copy, and says how many it skipped', () => {
        const blockedTool: GetMcpToolRequest = { ...MCP_TOOL, id: 10, name: 'Secret MCP' };
        const toast = { error: vi.fn(), success: vi.fn(), info: vi.fn() };
        const port = {
            kind: 'mcp',
            entityLabel: 'MCP tool',
            entityLabelPlural: 'MCP tools',
            filterAdapter: {
                idOf: (tool: GetMcpToolRequest) => tool.id,
                nameOf: (tool: GetMcpToolRequest) => tool.name,
                labelIdsOf: (tool: GetMcpToolRequest) => tool.labels,
                favoriteOf: (tool: GetMcpToolRequest) => tool.is_favorite,
                searchableTextOf: (tool: GetMcpToolRequest) => [tool.name],
                updatedAtOf: (tool: GetMcpToolRequest) => tool.updated_at,
            },
            createdEvent$: NEVER,
            isBuiltIn: () => false,
            descriptionOf: () => '',
            getAll: () => of([MCP_TOOL, blockedTool]),
            getBulkUsage: () => of([]),
            copyBlockedReason: (tool: GetMcpToolRequest) =>
                tool.id === blockedTool.id ? 'This code reads secrets.' : undefined,
            copy: (id: number) => of({ ...MCP_TOOL, id: id + 100, name: `Copy of ${id}` }),
        };
        TestBed.configureTestingModule({
            providers: [
                provideHttpClient(),
                provideHttpClientTesting(),
                provideRouter([]),
                { provide: TOOLS_LIST_PORT, useValue: port },
                { provide: ToastService, useValue: toast },
            ],
        });
        const fixture = TestBed.createComponent(ToolsListComponent);
        fixture.detectChanges();
        const viewState = TestBed.inject(ToolsViewStorageService);
        viewState.setSelected(MCP_TOOL.id, true);
        viewState.setSelected(blockedTool.id, true);

        viewState.dispatch({ kind: 'duplicate' });

        expect(toast.info).toHaveBeenCalledExactlyOnceWith(
            '1 MCP tool(s) read secrets you may not use and will not be duplicated.'
        );
        expect(toast.success).toHaveBeenCalledExactlyOnceWith('Duplicated 1 MCP tool(s).');
    });
});

describe('ToolsListComponent ?toolId= deep link', () => {
    async function openAt(url: string): Promise<{ openConfigureDialog: ReturnType<typeof vi.fn>; router: Router }> {
        const openConfigureDialog = vi.fn(() => ({ closed: NEVER }));
        const port = {
            kind: 'mcp',
            entityLabelPlural: 'MCP tools',
            filterAdapter: {
                idOf: (tool: GetMcpToolRequest) => tool.id,
                nameOf: (tool: GetMcpToolRequest) => tool.name,
                labelIdsOf: (tool: GetMcpToolRequest) => tool.labels,
                favoriteOf: (tool: GetMcpToolRequest) => tool.is_favorite,
                searchableTextOf: (tool: GetMcpToolRequest) => [tool.name],
                updatedAtOf: (tool: GetMcpToolRequest) => tool.updated_at,
            },
            createdEvent$: NEVER,
            isBuiltIn: () => false,
            descriptionOf: () => '',
            getAll: () => of([MCP_TOOL]),
            getBulkUsage: () => of([]),
            openConfigureDialog,
        };
        TestBed.configureTestingModule({
            providers: [
                provideHttpClient(),
                provideHttpClientTesting(),
                provideRouter([{ path: 'tools/mcp', component: ToolsListComponent }]),
                { provide: TOOLS_LIST_PORT, useValue: port },
            ],
        });
        const harness = await RouterTestingHarness.create();
        await harness.navigateByUrl(url);
        await harness.fixture.whenStable();
        return { openConfigureDialog, router: TestBed.inject(Router) };
    }

    it('opens the tool as a card click does, and drops the param from the URL', async () => {
        const { openConfigureDialog, router } = await openAt(`/tools/mcp?toolId=${MCP_TOOL.id}`);

        expect(openConfigureDialog).toHaveBeenCalledExactlyOnceWith(expect.anything(), MCP_TOOL);
        expect(router.url).toBe('/tools/mcp');
    });

    it('opens nothing for a tool id that is not in the list', async () => {
        const { openConfigureDialog } = await openAt('/tools/mcp?toolId=999');

        expect(openConfigureDialog).not.toHaveBeenCalled();
    });
});
