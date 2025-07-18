import { Injectable } from '@angular/core';
import { forkJoin, map, Observable } from 'rxjs';
import { TasksService } from './tasks.service';
import { AgentsService } from './staff.service';
import { ToolConfigService } from './tool_config.service';
import { PythonCodeToolService } from '../user-settings-page/tools/custom-tool-editor/services/pythonCodeToolService.service';
import { ToolsService } from '../features/tools/services/tools.service';
import { FullTask } from '../shared/models/full-task.model';
import { GetTaskRequest } from '../shared/models/task.model';
import { GetAgentRequest } from '../shared/models/agent.model';
import { GetToolConfigRequest } from '../features/tools/models/tool_config.model';
import { GetPythonCodeToolRequest } from '../features/tools/models/python-code-tool.model';
import { Tool } from '../features/tools/models/tool.model';

export interface TableFullTask extends Omit<FullTask, 'id'> {
  id: number | string;
}

@Injectable({
  providedIn: 'root',
})
export class FullTaskService {
  constructor(
    private tasksService: TasksService,
    private agentsService: AgentsService,
    private toolConfigService: ToolConfigService,
    private pythonCodeToolService: PythonCodeToolService,
    private toolsService: ToolsService
  ) {}

  getFullTasks(): Observable<FullTask[]> {
    return forkJoin({
      tasks: this.tasksService.getTasks(),
      agents: this.agentsService.getAgents(),
      toolConfigs: this.toolConfigService.getToolConfigs(),
      pythonTools: this.pythonCodeToolService.getPythonCodeTools(),
      tools: this.toolsService.getTools(),
    }).pipe(
      map(({ tasks, agents, toolConfigs, pythonTools, tools }) => {
        // Create agent lookup map
        const agentMap = new Map<number, GetAgentRequest>();
        agents.forEach((agent) => {
          agentMap.set(agent.id, agent);
        });

        // Create tool lookup map
        const toolsMap = new Map<number, string>();
        tools.forEach((tool: Tool) => {
          toolsMap.set(tool.id, tool.name);
        });

        return tasks.map((task) => {
          // Get agent data
          const agentData = task.agent
            ? agentMap.get(task.agent) || null
            : null;

          // Parse tools from the unified tools array
          const configuredToolIds: number[] = [];
          const pythonToolIds: number[] = [];

          task.tools.forEach((tool) => {
            if (tool.unique_name.startsWith('configured-tool:')) {
              configuredToolIds.push(tool.data.id);
            } else if (tool.unique_name.startsWith('python-code-tool:')) {
              pythonToolIds.push(tool.data.id);
            }
          });

          // Get full tool configs based on parsed IDs
          const fullConfiguredTools = toolConfigs.filter((tool) =>
            configuredToolIds.includes(tool.id)
          );
          const fullPythonTools = pythonTools.filter((pt) =>
            pythonToolIds.includes(pt.id)
          );

          // Create merged tools with configName and toolName
          const mergedTools = [
            ...fullConfiguredTools.map((tc) => ({
              id: tc.id,
              configName: tc.name, // This is the config name
              toolName: toolsMap.get(tc.tool) || 'Unknown Tool', // This is the actual tool name
              type: 'tool-config',
            })),
            ...fullPythonTools.map((pt) => ({
              id: pt.id,
              configName: pt.name, // For python tools, the name is both config and tool name
              toolName: pt.name, // Python tools have the same name for both
              type: 'python-tool',
            })),
          ];

          return {
            ...task,
            agentData,
            mergedTools,
          };
        });
      })
    );
  }

  getFullTasksByProject(projectId: number): Observable<FullTask[]> {
    return forkJoin({
      tasks: this.tasksService.getTasksByProjectId(projectId.toString()),
      agents: this.agentsService.getAgents(),
      toolConfigs: this.toolConfigService.getToolConfigs(),
      pythonTools: this.pythonCodeToolService.getPythonCodeTools(),
      tools: this.toolsService.getTools(),
    }).pipe(
      map(({ tasks, agents, toolConfigs, pythonTools, tools }) => {
        // Create agent lookup map
        const agentMap = new Map<number, GetAgentRequest>();
        agents.forEach((agent) => {
          agentMap.set(agent.id, agent);
        });

        // Create tool lookup map
        const toolsMap = new Map<number, string>();
        tools.forEach((tool: Tool) => {
          toolsMap.set(tool.id, tool.name);
        });

        return tasks.map((task) => {
          // Get agent data
          const agentData = task.agent
            ? agentMap.get(task.agent) || null
            : null;

          // Parse tools from the unified tools array
          const configuredToolIds: number[] = [];
          const pythonToolIds: number[] = [];

          task.tools.forEach((tool) => {
            if (tool.unique_name.startsWith('configured-tool:')) {
              configuredToolIds.push(tool.data.id);
            } else if (tool.unique_name.startsWith('python-code-tool:')) {
              pythonToolIds.push(tool.data.id);
            }
          });

          // Get full tool configs based on parsed IDs
          const fullConfiguredTools = toolConfigs.filter((tool) =>
            configuredToolIds.includes(tool.id)
          );
          const fullPythonTools = pythonTools.filter((pt) =>
            pythonToolIds.includes(pt.id)
          );

          // Create merged tools with configName and toolName
          const mergedTools = [
            ...fullConfiguredTools.map((tc) => ({
              id: tc.id,
              configName: tc.name, // This is the config name
              toolName: toolsMap.get(tc.tool) || 'Unknown Tool', // This is the actual tool name
              type: 'tool-config',
            })),
            ...fullPythonTools.map((pt) => ({
              id: pt.id,
              configName: pt.name, // For python tools, the name is both config and tool name
              toolName: pt.name, // Python tools have the same name for both
              type: 'python-tool',
            })),
          ];

          return {
            ...task,
            agentData,
            mergedTools,
          };
        });
      })
    );
  }

  getFullTaskById(taskId: number): Observable<FullTask | null> {
    return forkJoin({
      task: this.tasksService.getTaskById(taskId),
      agents: this.agentsService.getAgents(),
      toolConfigs: this.toolConfigService.getToolConfigs(),
      pythonTools: this.pythonCodeToolService.getPythonCodeTools(),
      tools: this.toolsService.getTools(),
    }).pipe(
      map(({ task, agents, toolConfigs, pythonTools, tools }) => {
        if (!task) {
          return null;
        }

        // Create agent lookup map
        const agentMap = new Map<number, GetAgentRequest>();
        agents.forEach((agent) => {
          agentMap.set(agent.id, agent);
        });

        // Create tool lookup map
        const toolsMap = new Map<number, string>();
        tools.forEach((tool: Tool) => {
          toolsMap.set(tool.id, tool.name);
        });

        // Get agent data
        const agentData = task.agent ? agentMap.get(task.agent) || null : null;

        // Parse tools from the unified tools array
        const configuredToolIds: number[] = [];
        const pythonToolIds: number[] = [];

        task.tools.forEach((tool) => {
          if (tool.unique_name.startsWith('configured-tool:')) {
            configuredToolIds.push(tool.data.id);
          } else if (tool.unique_name.startsWith('python-code-tool:')) {
            pythonToolIds.push(tool.data.id);
          }
        });

        // Get full tool configs based on parsed IDs
        const fullConfiguredTools = toolConfigs.filter((tool) =>
          configuredToolIds.includes(tool.id)
        );
        const fullPythonTools = pythonTools.filter((pt) =>
          pythonToolIds.includes(pt.id)
        );

        // Create merged tools with configName and toolName
        const mergedTools = [
          ...fullConfiguredTools.map((tc) => ({
            id: tc.id,
            configName: tc.name, // This is the config name
            toolName: toolsMap.get(tc.tool) || 'Unknown Tool', // This is the actual tool name
            type: 'tool-config',
          })),
          ...fullPythonTools.map((pt) => ({
            id: pt.id,
            configName: pt.name, // For python tools, the name is both config and tool name
            toolName: pt.name, // Python tools have the same name for both
            type: 'python-tool',
          })),
        ];

        return {
          ...task,
          agentData,
          mergedTools,
        };
      })
    );
  }
}
