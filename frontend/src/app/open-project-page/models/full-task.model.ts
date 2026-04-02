import { GetAgentRequest } from '../../features/staff/models/agent.model';
import { GetTaskRequest } from '../../features/tasks/models/task.model';

export interface FullTask extends GetTaskRequest {
    agentData: GetAgentRequest | null;
}
