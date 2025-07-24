import { ToolUniqueName } from '../models/agent.model';

export function buildToolIdsArray(
  configuredToolIds: number[],
  pythonToolIds: number[]
): ToolUniqueName[] {
  const toolIds: ToolUniqueName[] = [];

  configuredToolIds.forEach((id) => {
    toolIds.push(`configured-tool:${id}`);
  });

  pythonToolIds.forEach((id) => {
    toolIds.push(`python-code-tool:${id}`);
  });

  return toolIds;
}
