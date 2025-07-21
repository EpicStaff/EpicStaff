export interface SessionStatusMessageData {
  status: string;
  crew_id: number;
  status_data: {
    name: string;
    execution_order: number;
  };
  message_type: 'update_session_status';
}
