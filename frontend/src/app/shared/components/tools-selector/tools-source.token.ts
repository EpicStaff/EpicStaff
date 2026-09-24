import { InjectionToken } from '@angular/core';
import { GetMcpToolRequest, GetPythonCodeToolRequest } from '@shared/models';
import { Observable } from 'rxjs';

export interface ToolsSource {
    getPythonCodeTools(): Observable<GetPythonCodeToolRequest[]>;
    getMcpTools(): Observable<GetMcpToolRequest[]>;
}

export const TOOLS_SOURCE = new InjectionToken<ToolsSource>('TOOLS_SOURCE');
