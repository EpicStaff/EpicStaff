// Mirrors sanitize_tool_name in src/agent/app/tools/registry_builder.py - keep the step order.
export function sanitizeToolName(name: string): string {
    const cleaned = name
        .replace(/[^A-Za-z0-9_-]/g, '_')
        .replace(/^_+|_+$/g, '')
        .slice(0, 64);
    return cleaned || 'tool';
}
