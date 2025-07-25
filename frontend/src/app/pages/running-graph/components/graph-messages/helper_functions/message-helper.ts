import {
  GraphMessage,
  MessageType,
} from '../../../models/graph-session-message.model';

export function isMessageType(
  message: GraphMessage,
  type: MessageType
): boolean {
  return message.message_data?.message_type === type;
}
