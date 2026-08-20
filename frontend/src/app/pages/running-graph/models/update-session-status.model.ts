import { MessageType } from './graph-session-message.model';

export interface SessionStatusMessageData {
    status: string;
    crew_id: number;
    status_data: {
        name: string;
        execution_order: number;
    };
    message_type: MessageType.UPDATE_SESSION_STATUS;
}
