import { inject, Injectable } from '@angular/core';
import { ToolsSource } from '@shared/components';
import { GetMcpToolRequest, GetPythonCodeToolRequest } from '@shared/models';
import { Observable } from 'rxjs';

import { CustomToolsService } from './custom-tools/custom-tools.service';
import { McpToolsService } from './mcp-tools/mcp-tools.service';

@Injectable({
    providedIn: 'root',
})
export class ToolsSourceService implements ToolsSource {
    private readonly customTools = inject(CustomToolsService);
    private readonly mcpTools = inject(McpToolsService);

    public getPythonCodeTools(): Observable<GetPythonCodeToolRequest[]> {
        return this.customTools.getPythonCodeTools();
    }

    public getMcpTools(): Observable<GetMcpToolRequest[]> {
        return this.mcpTools.getMcpTools();
    }
}
