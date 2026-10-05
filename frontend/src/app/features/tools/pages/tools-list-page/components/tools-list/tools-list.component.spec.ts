import { provideHttpClient } from '@angular/common/http';
import { provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { AuthorshipDetailsDialogService } from '@shared/components';
import { GetMcpToolRequest } from '@shared/models';
import { NEVER, of } from 'rxjs';

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
    it('opens "Tool Details" with the authorship of the chosen tool', () => {
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

        fixture.componentInstance.onCardMenuAction({ tool: MCP_CARD, action: 'view_details' });

        expect(authorshipDetailsDialog.open).toHaveBeenCalledWith('Tool Details', MCP_TOOL);
    });
});
