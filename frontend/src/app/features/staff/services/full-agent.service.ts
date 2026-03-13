import { Injectable } from '@angular/core';
import { forkJoin, Observable } from 'rxjs';
import { map } from 'rxjs/operators';

import { AgentsService } from './staff.service';
import { LLM_Config_Service } from '../../settings-dialog/services/llms/llm-config.service';
import { ToolConfigService } from '../../tools/services/tool-config.service';
import { PythonCodeToolService } from '../../../user-settings-page/tools/custom-tool-editor/services/pythonCodeToolService.service';
import { LLM_Models_Service } from '../../settings-dialog/services/llms/llm-models.service';
import { ProjectsStorageService } from '../../projects/services/projects-storage.service';
import { LLM_Providers_Service } from '../../settings-dialog/services/llm-providers.service';
import { McpToolsService } from '../../tools/services/mcp-tools/mcp-tools.service';

import { GetAgentRequest, PartialUpdateAgentRequest } from '../models/agent.model';
import { GetToolConfigRequest } from '../../tools/models/tool-config.model';
import { GetPythonCodeToolRequest } from '../../tools/models/python-code-tool.model';
import { GetMcpToolRequest } from '../../tools/models/mcp-tool.model';
import { RealtimeModelConfigsService } from '../../settings-dialog/services/realtime-llms/real-time-model-config.service';
import { RealtimeModelsService } from '../../settings-dialog/services/realtime-llms/real-time-models.service';
import { LLM_Provider } from '../../settings-dialog/models/llm-provider.model';
import { FullLLMConfig } from '../../settings-dialog/services/llms/full-llm-config.service';
import { FullRealtimeConfig } from '../../settings-dialog/services/realtime-llms/full-reamtime-config.service';
import { Tool } from '../../tools/models/tool.model';

export interface MergedConfig {
  id: number;
  custom_name: string;
  model_name: string;
  type: 'llm' | 'realtime';
  provider_id?: number;
  provider_name?: string;
}

export interface PartialAgent extends Partial<PartialUpdateAgentRequest> {
  fullLlmConfig?: FullLLMConfig | null;
  fullFcmLlmConfig?: FullLLMConfig | null;
  fullRealtimeConfig?: FullRealtimeConfig | null;
  fullConfiguredTools?: GetToolConfigRequest[];
  fullPythonTools?: GetPythonCodeToolRequest[];
  fullMcpTools?: GetMcpToolRequest[];
  mergedTools?: {
    id: number;
    configName: string;
    toolName: string;
    type: string;
  }[];
  mergedConfigs?: MergedConfig[];
  tags?: string[];
}


export interface FullAgent extends GetAgentRequest {
  fullLlmConfig?: FullLLMConfig | null;
  fullFcmLlmConfig?: FullLLMConfig | null;
  fullRealtimeConfig?: FullRealtimeConfig | null;
  fullConfiguredTools: GetToolConfigRequest[];
  fullPythonTools: GetPythonCodeToolRequest[];
  fullMcpTools: GetMcpToolRequest[];
  mergedTools: {
    id: number;
    configName: string;
    toolName: string;
    type: string;
  }[];
  mergedConfigs: MergedConfig[];
  tags: string[];
}

export interface TableFullAgent extends Omit<FullAgent, 'id'> {
  id: number | string;
}

@Injectable({
  providedIn: 'root',
})
export class FullAgentService {
  constructor(
    private agentsService: AgentsService,
    private llmConfigService: LLM_Config_Service,
    private toolConfigService: ToolConfigService,
    private pythonCodeToolService: PythonCodeToolService,
    private llmModelsService: LLM_Models_Service,
    private projectsService: ProjectsStorageService,
    private realtimeModelConfigsService: RealtimeModelConfigsService,
    private realtimeModelsService: RealtimeModelsService,
    private llmProvidersService: LLM_Providers_Service,
    private mcpToolsService: McpToolsService
  ) {}

  getFullAgents(): Observable<FullAgent[]> {
    return forkJoin({
      agents: this.agentsService.getAgents(),
      llmConfigs: this.llmConfigService.getAllConfigsLLM(),
      toolConfigs: this.toolConfigService.getToolConfigs(),
      pythonTools: this.pythonCodeToolService.getPythonCodeTools(),
      mcpTools: this.mcpToolsService.getMcpTools(),
      llmModels: this.llmModelsService.getLLMModels(),
      realtimeConfigs: this.realtimeModelConfigsService.getAllConfigs(),
      realtimeModels: this.realtimeModelsService.getAllModels(),
      llmProviders: this.llmProvidersService.getProviders(),
    }).pipe(
      map(
        ({
          agents,
          llmConfigs,
          toolConfigs,
          pythonTools,
          mcpTools,
          llmModels,
          realtimeConfigs,
          realtimeModels,
          llmProviders,
        }) => {
          // Build lookup tables for models and providers
          const modelMap: Record<number, any> = {};
          llmModels.forEach((model) => {
            modelMap[model.id] = model;
          });

          const realtimeModelMap: Record<number, any> = {};
          realtimeModels.forEach((model) => {
            realtimeModelMap[model.id] = model;
          });

          const providerMap: Record<number, LLM_Provider> = {};
          llmProviders.forEach((provider) => {
            providerMap[provider.id] = provider;
          });

          return agents.map((agent) => {
            const findEnhancedLlmConfig = (
              configId: number | null
            ): FullLLMConfig | null => {
              if (configId === null) return null;
              const config = llmConfigs.find((cfg) => cfg.id === configId);
              if (config) {
                const model = modelMap[config.model] || null;
                const provider = model?.llm_provider
                  ? providerMap[model.llm_provider]
                  : null;

                return {
                  ...config,
                  modelDetails: model,
                  providerDetails: provider,
                };
              }
              return null;
            };

            const findEnhancedRealtimeConfig = (
              configId: number | null
            ): FullRealtimeConfig | null => {
              if (configId === null) return null;
              const config = realtimeConfigs.find((cfg) => cfg.id === configId);
              if (config) {
                const model = realtimeModelMap[config.realtime_model] || null;
                const provider = model?.provider
                  ? providerMap[model.provider]
                  : null;

                return {
                  ...config,
                  modelDetails: model,
                  providerDetails: provider,
                };
              }
              return null;
            };

            // Use the helper functions, ensuring they don't receive `null`
            const fullLlmConfig = findEnhancedLlmConfig(agent.llm_config);
            const fullFcmLlmConfig = findEnhancedLlmConfig(
              agent.fcm_llm_config
            );
            const fullRealtimeConfig = findEnhancedRealtimeConfig(
              agent.realtime_agent?.realtime_config
            );

            // Parse tools from the unified tools array
            const configuredToolIds: number[] = [];
            const pythonToolIds: number[] = [];
            const mcpToolIds: number[] = [];

            if (agent.tools && Array.isArray(agent.tools)) {
              agent.tools.forEach((tool) => {
                if (tool.unique_name.startsWith('configured-tool:')) {
                  configuredToolIds.push(tool.data.id);
                } else if (tool.unique_name.startsWith('python-code-tool:')) {
                  pythonToolIds.push(tool.data.id);
                } else if (tool.unique_name.startsWith('mcp-tool:')) {
                  mcpToolIds.push(tool.data.id);
                }
              });
            }

            // Tool configs based on parsed IDs
            const fullConfiguredTools = toolConfigs.filter((tool) =>
              configuredToolIds.includes(tool.id)
            );
            const fullPythonTools = pythonTools.filter((pt) =>
              pythonToolIds.includes(pt.id)
            );
            const fullMcpTools = mcpTools.filter((mcp: GetMcpToolRequest) =>
              mcpToolIds.includes(mcp.id)
            );

            // Merge all sets of tools
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

            // Merge LLM and realtime configs
            const mergedConfigs: MergedConfig[] = [];

            if (fullLlmConfig) {
              mergedConfigs.push({
                id: fullLlmConfig.id,
                custom_name: fullLlmConfig.custom_name,
                model_name: fullLlmConfig.modelDetails?.name || 'Unknown Model',
                type: 'llm',
                provider_id: fullLlmConfig.modelDetails?.llm_provider,
                provider_name:
                  fullLlmConfig.providerDetails?.name || 'Unknown Provider',
              });
            }

            if (fullRealtimeConfig) {
              mergedConfigs.push({
                id: fullRealtimeConfig.id,
                custom_name: fullRealtimeConfig.custom_name,
                model_name:
                  fullRealtimeConfig.modelDetails?.name || 'Unknown Model',
                type: 'realtime',
                provider_id: fullRealtimeConfig.modelDetails?.provider,
                provider_name:
                  fullRealtimeConfig.providerDetails?.name ||
                  'Unknown Provider',
              });
            }

            return {
              ...agent,
              configured_tools: configuredToolIds, // For backward compatibility
              python_code_tools: pythonToolIds, // For backward compatibility
              mcp_tools: mcpToolIds, // MCP tools IDs
              fullLlmConfig,
              fullFcmLlmConfig,
              fullRealtimeConfig,
              fullConfiguredTools,
              fullPythonTools,
              fullMcpTools,
              mergedTools,
              mergedConfigs,
              tags: [], // Empty array instead of random tags
            };
          });
        }
      )
    );
  }

  getFullAgentsByProject(projectId: number): Observable<FullAgent[]> {
    // Fetch project and all other data concurrently
    return forkJoin({
      project: this.projectsService.getProjectById(projectId),
      agents: this.agentsService.getAgentsByProjectId(projectId),
      llmConfigs: this.llmConfigService.getAllConfigsLLM(),
      toolConfigs: this.toolConfigService.getToolConfigs(),
      pythonTools: this.pythonCodeToolService.getPythonCodeTools(),
      mcpTools: this.mcpToolsService.getMcpTools(),
      llmModels: this.llmModelsService.getLLMModels(),
      realtimeConfigs: this.realtimeModelConfigsService.getAllConfigs(),
      realtimeModels: this.realtimeModelsService.getAllModels(),
      llmProviders: this.llmProvidersService.getProviders(),
    }).pipe(
      map(
        ({
          project,
          agents,
          llmConfigs,
          toolConfigs,
          pythonTools,
          mcpTools,
          llmModels,
          realtimeConfigs,
          realtimeModels,
          llmProviders,
        }) => {
          // Build lookup tables for models and providers
          const modelMap: Record<number, any> = {};
          llmModels.forEach((model) => {
            modelMap[model.id] = model;
          });

          const realtimeModelMap: Record<number, any> = {};
          realtimeModels.forEach((model) => {
            realtimeModelMap[model.id] = model;
          });

          const providerMap: Record<number, LLM_Provider> = {};
          llmProviders.forEach((provider) => {
            providerMap[provider.id] = provider;
          });

          // Filter agents to include only those related to the project
          const projectAgentIds = project?.agents || []; // Agents field from the project

          const filteredAgents = agents.filter(
            (agent) => projectAgentIds.includes(agent.id) // Keep only agents present in the project
          );

          return filteredAgents.map((agent) => {
            const findEnhancedLlmConfig = (
              configId: number | null
            ): FullLLMConfig | null => {
              if (configId === null) return null;
              const config = llmConfigs.find((cfg) => cfg.id === configId);
              if (config) {
                const model = modelMap[config.model] || null;
                const provider = model?.llm_provider
                  ? providerMap[model.llm_provider]
                  : null;

                return {
                  ...config,
                  modelDetails: model,
                  providerDetails: provider,
                };
              }
              return null;
            };

            const findEnhancedRealtimeConfig = (
              configId: number | null
            ): FullRealtimeConfig | null => {
              if (configId === null) return null;
              const config = realtimeConfigs.find((cfg) => cfg.id === configId);
              if (config) {
                const model = realtimeModelMap[config.realtime_model] || null;
                const provider = model?.provider
                  ? providerMap[model.provider]
                  : null;

                return {
                  ...config,
                  modelDetails: model,
                  providerDetails: provider,
                };
              }
              return null;
            };

            // Use the helper functions
            const fullLlmConfig = findEnhancedLlmConfig(agent.llm_config);
            const fullFcmLlmConfig = findEnhancedLlmConfig(
              agent.fcm_llm_config
            );
            const fullRealtimeConfig = findEnhancedRealtimeConfig(
              agent.realtime_agent?.realtime_config
            );

            // Parse tools from the unified tools array
            const configuredToolIds: number[] = [];
            const pythonToolIds: number[] = [];
            const mcpToolIds: number[] = [];

            if (agent.tools && Array.isArray(agent.tools)) {
              agent.tools.forEach((tool) => {
                if (tool.unique_name.startsWith('configured-tool:')) {
                  configuredToolIds.push(tool.data.id);
                } else if (tool.unique_name.startsWith('python-code-tool:')) {
                  pythonToolIds.push(tool.data.id);
                } else if (tool.unique_name.startsWith('mcp-tool:')) {
                  mcpToolIds.push(tool.data.id);
                }
              });
            }

            // Tool configs based on parsed IDs
            const fullConfiguredTools = toolConfigs.filter((tool) =>
              configuredToolIds.includes(tool.id)
            );
            const fullPythonTools = pythonTools.filter((pt) =>
              pythonToolIds.includes(pt.id)
            );
            const fullMcpTools = mcpTools.filter((mcp: GetMcpToolRequest) =>
              mcpToolIds.includes(mcp.id)
            );

            // Merge all sets of tools
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

            // Merge LLM and realtime configs
            const mergedConfigs: MergedConfig[] = [];

            if (fullLlmConfig) {
              mergedConfigs.push({
                id: fullLlmConfig.id,
                custom_name: fullLlmConfig.custom_name,
                model_name: fullLlmConfig.modelDetails?.name || 'Unknown Model',
                type: 'llm',
                provider_id: fullLlmConfig.modelDetails?.llm_provider,
                provider_name:
                  fullLlmConfig.providerDetails?.name || 'Unknown Provider',
              });
            }

            if (fullRealtimeConfig) {
              mergedConfigs.push({
                id: fullRealtimeConfig.id,
                custom_name: fullRealtimeConfig.custom_name,
                model_name:
                  fullRealtimeConfig.modelDetails?.name || 'Unknown Model',
                type: 'realtime',
                provider_id: fullRealtimeConfig.modelDetails?.provider,
                provider_name:
                  fullRealtimeConfig.providerDetails?.name ||
                  'Unknown Provider',
              });
            }

            return {
              ...agent,
              configured_tools: configuredToolIds, // For backward compatibility
              python_code_tools: pythonToolIds, // For backward compatibility
              mcp_tools: mcpToolIds, // MCP tools IDs
              fullLlmConfig,
              fullFcmLlmConfig,
              fullRealtimeConfig,
              fullConfiguredTools,
              fullPythonTools,
              fullMcpTools,
              mergedTools,
              mergedConfigs,
              tags: [], // Empty array instead of random tags
            };
          });
        }
      )
    );
  }

  getFullAgentById(agentId: number): Observable<FullAgent | null> {
    return forkJoin({
      agents: this.agentsService.getAgents(),
      llmConfigs: this.llmConfigService.getAllConfigsLLM(),
      toolConfigs: this.toolConfigService.getToolConfigs(),
      pythonTools: this.pythonCodeToolService.getPythonCodeTools(),
      mcpTools: this.mcpToolsService.getMcpTools(),
      llmModels: this.llmModelsService.getLLMModels(),
      realtimeConfigs: this.realtimeModelConfigsService.getAllConfigs(),
      realtimeModels: this.realtimeModelsService.getAllModels(),
      llmProviders: this.llmProvidersService.getProviders(),
    }).pipe(
      map(
        ({
          agents,
          llmConfigs,
          toolConfigs,
          pythonTools,
          mcpTools,
          llmModels,
          realtimeConfigs,
          realtimeModels,
          llmProviders,
        }) => {
          // Find the agent with the specified ID
          const agent = agents.find((agent) => agent.id === agentId);

          // If no agent is found, return null
          if (!agent) {
            return null;
          }

          // Build lookup tables for models and providers
          const modelMap: Record<number, any> = {};
          llmModels.forEach((model) => {
            modelMap[model.id] = model;
          });

          const realtimeModelMap: Record<number, any> = {};
          realtimeModels.forEach((model) => {
            realtimeModelMap[model.id] = model;
          });

          const providerMap: Record<number, LLM_Provider> = {};
          llmProviders.forEach((provider) => {
            providerMap[provider.id] = provider;
          });

          const findEnhancedLlmConfig = (
            configId: number | null
          ): FullLLMConfig | null => {
            if (configId === null) return null;
            const config = llmConfigs.find((cfg) => cfg.id === configId);
            if (config) {
              const model = modelMap[config.model] || null;
              const provider = model?.llm_provider
                ? providerMap[model.llm_provider]
                : null;

              return {
                ...config,
                modelDetails: model,
                providerDetails: provider,
              };
            }
            return null;
          };

          const findEnhancedRealtimeConfig = (
            configId: number | null
          ): FullRealtimeConfig | null => {
            if (configId === null) return null;
            const config = realtimeConfigs.find((cfg) => cfg.id === configId);
            if (config) {
              const model = realtimeModelMap[config.realtime_model] || null;
              const provider = model?.provider
                ? providerMap[model.provider]
                : null;

              return {
                ...config,
                modelDetails: model,
                providerDetails: provider,
              };
            }
            return null;
          };

          // Use the helper functions
          const fullLlmConfig = findEnhancedLlmConfig(agent.llm_config);
          const fullFcmLlmConfig = findEnhancedLlmConfig(agent.fcm_llm_config);
          const fullRealtimeConfig = findEnhancedRealtimeConfig(
            agent.realtime_agent?.realtime_config
          );

          // Parse tools from the unified tools array
          const configuredToolIds: number[] = [];
          const pythonToolIds: number[] = [];
          const mcpToolIds: number[] = [];

          if (agent.tools && Array.isArray(agent.tools)) {
            agent.tools.forEach((tool) => {
              if (tool.unique_name.startsWith('configured-tool:')) {
                configuredToolIds.push(tool.data.id);
              } else if (tool.unique_name.startsWith('python-code-tool:')) {
                pythonToolIds.push(tool.data.id);
              } else if (tool.unique_name.startsWith('mcp-tool:')) {
                mcpToolIds.push(tool.data.id);
              }
            });
          }

          // Tool configs based on parsed IDs
          const fullConfiguredTools = toolConfigs.filter((tool) =>
            configuredToolIds.includes(tool.id)
          );
          const fullPythonTools = pythonTools.filter((pt) =>
            pythonToolIds.includes(pt.id)
          );
          const fullMcpTools = mcpTools.filter((mcp: GetMcpToolRequest) =>
            mcpToolIds.includes(mcp.id)
          );

          // Merge all sets of tools
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

          // Merge LLM and realtime configs
          const mergedConfigs: MergedConfig[] = [];

          if (fullLlmConfig) {
            mergedConfigs.push({
              id: fullLlmConfig.id,
              custom_name: fullLlmConfig.custom_name,
              model_name: fullLlmConfig.modelDetails?.name || 'Unknown Model',
              type: 'llm',
              provider_id: fullLlmConfig.modelDetails?.llm_provider,
              provider_name:
                fullLlmConfig.providerDetails?.name || 'Unknown Provider',
            });
          }

          if (fullRealtimeConfig) {
            mergedConfigs.push({
              id: fullRealtimeConfig.id,
              custom_name: fullRealtimeConfig.custom_name,
              model_name:
                fullRealtimeConfig.modelDetails?.name || 'Unknown Model',
              type: 'realtime',
              provider_id: fullRealtimeConfig.modelDetails?.provider,
              provider_name:
                fullRealtimeConfig.providerDetails?.name || 'Unknown Provider',
            });
          }

          return {
            ...agent,
            configured_tools: configuredToolIds, // For backward compatibility
            python_code_tools: pythonToolIds, // For backward compatibility
            mcp_tools: mcpToolIds, // MCP tools IDs
            fullLlmConfig,
            fullFcmLlmConfig,
            fullRealtimeConfig,
            fullConfiguredTools,
            fullPythonTools,
            fullMcpTools,
            mergedTools,
            mergedConfigs,
            tags: [], // Empty array instead of random tags
          };
        }
      )
    );
  }
}
