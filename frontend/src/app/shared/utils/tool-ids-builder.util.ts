import { ToolUniqueName } from '../../features/staff/models/agent.model';

export function buildToolIdsArray(pythonToolIds: number[], mcpToolIds: number[] = []): ToolUniqueName[] {
    const toolIds: ToolUniqueName[] = [];

    pythonToolIds.forEach((id) => {
        toolIds.push(`python-code-tool:${id}`);
    });

    mcpToolIds.forEach((id) => {
        toolIds.push(`mcp-tool:${id}`);
    });

    return toolIds;
}
