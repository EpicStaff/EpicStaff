import { GetAgentRequest } from '../../staff/models/agent.model';
import { GetTaskRequest } from './task.model';

export interface FullTask extends GetTaskRequest {
  agentData: GetAgentRequest | null;
  mergedTools?: {
    id: number;
    configName: string;
    toolName: string;
    type: string;
  }[];
}
