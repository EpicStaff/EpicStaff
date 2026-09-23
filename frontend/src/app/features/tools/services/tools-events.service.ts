import { Injectable } from '@angular/core';
import { GetMcpToolRequest, GetPythonCodeToolRequest } from '@shared/models';
import { Subject } from 'rxjs';

@Injectable({
    providedIn: 'root',
})
export class ToolsEventsService {
    private mcpToolCreated = new Subject<GetMcpToolRequest>();
    private customToolCreated = new Subject<GetPythonCodeToolRequest>();

    public mcpToolCreated$ = this.mcpToolCreated.asObservable();
    public customToolCreated$ = this.customToolCreated.asObservable();

    public emitMcpToolCreated(tool: GetMcpToolRequest): void {
        this.mcpToolCreated.next(tool);
    }

    public emitCustomToolCreated(tool: GetPythonCodeToolRequest): void {
        this.customToolCreated.next(tool);
    }
}
