import { Injectable } from '@angular/core';
import { forkJoin, map, Observable } from 'rxjs';

import { GetAgentRequest } from '../../features/staff/models/agent.model';
import { AgentsService } from '../../features/staff/services/staff.service';
import { FullTask } from '../../features/tasks/models/full-task.model';
import { TasksService } from '../../features/tasks/services/tasks.service';
import { GetMcpToolRequest } from '../../features/tools/models/mcp-tool.model';
import { McpToolsService } from '../../features/tools/services/mcp-tools/mcp-tools.service';
import { ToolConfigService } from '../../features/tools/services/tool-config.service';
import { PythonCodeToolService } from '../../user-settings-page/tools/custom-tool-editor/services/pythonCodeToolService.service';

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
        private mcpToolsService: McpToolsService
    ) {}

    getFullTasks(): Observable<FullTask[]> {
        return forkJoin({
            tasks: this.tasksService.getTasks(),
            agents: this.agentsService.getAgents(),
            toolConfigs: this.toolConfigService.getToolConfigs(),
            pythonTools: this.pythonCodeToolService.getPythonCodeTools(),
            mcpTools: this.mcpToolsService.getMcpTools(),
        }).pipe(
            map(({ tasks, agents, toolConfigs, pythonTools, mcpTools }) => {
                // Create agent lookup map
                const agentMap = new Map<number, GetAgentRequest>();
                agents.forEach((agent) => {
                    agentMap.set(agent.id, agent);
                });

                return tasks.map((task) => {
                    // Get agent data
                    const agentData = task.agent ? agentMap.get(task.agent) || null : null;

                    // Parse tools from the unified tools array
                    const configuredToolIds: number[] = [];
                    const pythonToolIds: number[] = [];
                    const mcpToolIds: number[] = [];

                    task.tools.forEach((tool) => {
                        if (tool.unique_name.startsWith('configured-tool:')) {
                            configuredToolIds.push(tool.data.id);
                        } else if (tool.unique_name.startsWith('python-code-tool:')) {
                            pythonToolIds.push(tool.data.id);
                        } else if (tool.unique_name.startsWith('mcp-tool:')) {
                            mcpToolIds.push(tool.data.id);
                        }
                    });

                    // Get full tool configs based on parsed IDs
                    const fullConfiguredTools = toolConfigs.filter((tool) => configuredToolIds.includes(tool.id));
                    const fullPythonTools = pythonTools.filter((pt) => pythonToolIds.includes(pt.id));
                    const fullMcpTools = mcpTools.filter((mcp: GetMcpToolRequest) => mcpToolIds.includes(mcp.id));

                    // Create merged tools with configName and toolName
                    const mergedTools = [
                        ...fullConfiguredTools.map((tc) => ({
                            id: tc.id,
                            configName: tc.name, // This is the config name
                            toolName: 'Unknown Tool', // This is the actual tool name
                            type: 'tool-config',
                        })),
                        ...fullPythonTools.map((pt) => ({
                            id: pt.id,
                            configName: pt.name, // For python tools, the name is both config and tool name
                            toolName: pt.name, // Python tools have the same name for both
                            type: 'python-tool',
                        })),
                        ...fullMcpTools.map((mcp: GetMcpToolRequest) => ({
                            id: mcp.id,
                            configName: mcp.name, // MCP tool configuration name
                            toolName: mcp.tool_name, // MCP tool name
                            type: 'mcp-tool',
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
            mcpTools: this.mcpToolsService.getMcpTools(),
        }).pipe(
            map(({ tasks, agents, toolConfigs, pythonTools, mcpTools }) => {
                // Create agent lookup map
                const agentMap = new Map<number, GetAgentRequest>();
                agents.forEach((agent) => {
                    agentMap.set(agent.id, agent);
                });

                return tasks.map((task) => {
                    // Get agent data
                    const agentData = task.agent ? agentMap.get(task.agent) || null : null;

                    // Parse tools from the unified tools array
                    const configuredToolIds: number[] = [];
                    const pythonToolIds: number[] = [];
                    const mcpToolIds: number[] = [];

                    task.tools.forEach((tool) => {
                        if (tool.unique_name.startsWith('configured-tool:')) {
                            configuredToolIds.push(tool.data.id);
                        } else if (tool.unique_name.startsWith('python-code-tool:')) {
                            pythonToolIds.push(tool.data.id);
                        } else if (tool.unique_name.startsWith('mcp-tool:')) {
                            mcpToolIds.push(tool.data.id);
                        }
                    });

                    // Get full tool configs based on parsed IDs
                    const fullConfiguredTools = toolConfigs.filter((tool) => configuredToolIds.includes(tool.id));
                    const fullPythonTools = pythonTools.filter((pt) => pythonToolIds.includes(pt.id));
                    const fullMcpTools = mcpTools.filter((mcp: GetMcpToolRequest) => mcpToolIds.includes(mcp.id));

                    // Create merged tools with configName and toolName
                    const mergedTools = [
                        ...fullConfiguredTools.map((tc) => ({
                            id: tc.id,
                            configName: tc.name, // This is the config name
                            toolName: 'Unknown Tool', // This is the actual tool name
                            type: 'tool-config',
                        })),
                        ...fullPythonTools.map((pt) => ({
                            id: pt.id,
                            configName: pt.name, // For python tools, the name is both config and tool name
                            toolName: pt.name, // Python tools have the same name for both
                            type: 'python-tool',
                        })),
                        ...fullMcpTools.map((mcp: GetMcpToolRequest) => ({
                            id: mcp.id,
                            configName: mcp.name, // MCP tool configuration name
                            toolName: mcp.tool_name, // MCP tool name
                            type: 'mcp-tool',
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
            mcpTools: this.mcpToolsService.getMcpTools(),
        }).pipe(
            map(({ task, agents, toolConfigs, pythonTools, mcpTools }) => {
                if (!task) {
                    return null;
                }

                // Create agent lookup map
                const agentMap = new Map<number, GetAgentRequest>();
                agents.forEach((agent) => {
                    agentMap.set(agent.id, agent);
                });

                // Get agent data
                const agentData = task.agent ? agentMap.get(task.agent) || null : null;

                // Parse tools from the unified tools array
                const configuredToolIds: number[] = [];
                const pythonToolIds: number[] = [];
                const mcpToolIds: number[] = [];

                task.tools.forEach((tool) => {
                    if (tool.unique_name.startsWith('configured-tool:')) {
                        configuredToolIds.push(tool.data.id);
                    } else if (tool.unique_name.startsWith('python-code-tool:')) {
                        pythonToolIds.push(tool.data.id);
                    } else if (tool.unique_name.startsWith('mcp-tool:')) {
                        mcpToolIds.push(tool.data.id);
                    }
                });

                // Get full tool configs based on parsed IDs
                const fullConfiguredTools = toolConfigs.filter((tool) => configuredToolIds.includes(tool.id));
                const fullPythonTools = pythonTools.filter((pt) => pythonToolIds.includes(pt.id));
                const fullMcpTools = mcpTools.filter((mcp: GetMcpToolRequest) => mcpToolIds.includes(mcp.id));

                // Create merged tools with configName and toolName
                const mergedTools = [
                    ...fullConfiguredTools.map((tc) => ({
                        id: tc.id,
                        configName: tc.name, // This is the config name
                        toolName: 'Unknown Tool', // This is the actual tool name
                        type: 'tool-config',
                    })),
                    ...fullPythonTools.map((pt) => ({
                        id: pt.id,
                        configName: pt.name, // For python tools, the name is both config and tool name
                        toolName: pt.name, // Python tools have the same name for both
                        type: 'python-tool',
                    })),
                    ...fullMcpTools.map((mcp: GetMcpToolRequest) => ({
                        id: mcp.id,
                        configName: mcp.name, // MCP tool configuration name
                        toolName: mcp.tool_name, // MCP tool name
                        type: 'mcp-tool',
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
