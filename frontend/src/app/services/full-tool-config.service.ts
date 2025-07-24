import { HttpClient } from '@angular/common/http';
import { Injectable } from '@angular/core';
import { Observable, forkJoin, of, map, switchMap } from 'rxjs';
import { Tool } from '../features/tools/models/tool.model';
import { ToolsService } from '../features/tools/services/tools.service';
import { ToolConfigService } from './tool_config.service';
import {
  CreateToolConfigRequest,
  GetToolConfigRequest,
} from '../features/tools/models/tool_config.model';

export interface FullToolConfig extends Tool {
  toolConfigs: GetToolConfigRequest[]; // List of related tool configurations
}

@Injectable({
  providedIn: 'root',
})
export class FullToolConfigService {
  constructor(
    private http: HttpClient,
    private toolService: ToolsService,
    private toolConfigService: ToolConfigService
  ) {}

  // Fetch tools and their related tool configs in parallel, and create missing tool configs if needed
  // Only return configs for tools that have enabled = true
  getFullToolConfigs(): Observable<FullToolConfig[]> {
    return forkJoin({
      tools: this.toolService.getTools(),
      toolConfigs: this.toolConfigService.getToolConfigs(),
    }).pipe(
      switchMap(({ tools, toolConfigs }) => {
        // Filter only enabled tools
        const enabledTools = tools.filter((tool) => tool.enabled === true);

        // Filter tools that need configurations (only from enabled tools):
        const toolsNeedingConfigs = enabledTools.filter(
          (tool) =>
            tool.tool_fields.length === 0 && // Only tools with empty tool_fields
            !toolConfigs.some((config) => config.tool === tool.id) // And no existing configs
        );

        // If no tools need new configurations, return the updated tools directly
        if (toolsNeedingConfigs.length === 0) {
          const updatedTools = enabledTools.map((tool) => {
            const relatedToolConfigs = toolConfigs.filter(
              (config) => config.tool === tool.id
            );

            const updatedTool: FullToolConfig = {
              ...tool,
              toolConfigs: [...relatedToolConfigs],
            };

            return updatedTool;
          });

          return of(updatedTools);
        }

        // If there are tools that need configurations, create them in parallel
        const toolConfigCreationRequests = toolsNeedingConfigs.map((tool) =>
          this.createToolConfigForTool(tool)
        );

        return forkJoin(toolConfigCreationRequests).pipe(
          map((createdConfigs) => {
            // After creating the tool configs, associate them with their tools
            const updatedTools = enabledTools.map((tool) => {
              const relatedToolConfigs = toolConfigs.filter(
                (config) => config.tool === tool.id
              );

              // Add newly created tool configurations to the list
              const newToolConfigs = createdConfigs.filter(
                (newConfig) => newConfig.tool === tool.id
              );

              const updatedTool: FullToolConfig = {
                ...tool,
                toolConfigs: [...relatedToolConfigs, ...newToolConfigs],
              };

              return updatedTool;
            });

            return updatedTools;
          })
        );
      })
    );
  }

  // Create tool config for a specific tool if it doesn't have one
  private createToolConfigForTool(
    tool: Tool
  ): Observable<GetToolConfigRequest> {
    const createConfig: CreateToolConfigRequest = {
      name: `${tool.name}`,
      configuration: {},
      tool: tool.id,
    };

    return this.toolConfigService.createToolConfig(createConfig).pipe(
      map((response) => {
        return response;
      })
    );
  }
}
