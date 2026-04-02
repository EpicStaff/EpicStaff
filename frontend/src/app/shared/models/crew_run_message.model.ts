import { GetAgentRequest } from 'src/app/features/staff/models/agent.model';
import { AgentMessage } from 'src/app/pages/running-graph/models/agent-message.model';

import { TaskMessage } from './task-message.model';
import { UserMessage } from './user-message.model';

export interface CrewRunTaskMessage extends TaskMessage {
    type: 'task';
}

export interface CrewRunAgentMessage extends AgentMessage {
    type: 'agent';
    agentData: GetAgentRequest | null;
}
export interface CrewRunUserMessage extends UserMessage {
    type: 'user';
}
export type CrewRunMessage = CrewRunTaskMessage | CrewRunAgentMessage | CrewRunUserMessage;
