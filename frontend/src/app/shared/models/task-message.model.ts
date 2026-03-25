export interface TaskMessage {
  id: number;
  created_at: string;
  description: string;
  name: string;
  expected_output: string;
  raw: string;
  agent: string;
  session: number;
  task: number;
}
