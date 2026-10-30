import { HttpErrorResponse, provideHttpClient } from '@angular/common/http';
import { provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { AuthorshipDetailsDialogService } from '@shared/components';
import { GetMcpToolRequest } from '@shared/models';
import { NEVER, of, throwError } from 'rxjs';

import { ToastService } from '../../../../../../services/notifications';
import { ToolsViewStorageService } from '../../../../services/tools-view-storage.service';
import { ToolCardVM } from '../tool-card/tool-card.model';
import { ToolsListComponent } from './tools-list.component';
import { TOOLS_LIST_PORT } from './tools-list-port';

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
