export interface AgentMessage {
  id: number;
  created_at: string;
  thought: string;
  tool: string;
  tool_input: string;
  text: string;
  result: string;
  session: number;
  agent: number;
}
