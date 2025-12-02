import { Injectable } from '@angular/core';
import { Subject } from 'rxjs';
import { GetMcpToolRequest } from '../models/mcp-tool.model';
import { GetPythonCodeToolRequest } from '../models/python-code-tool.model';

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

