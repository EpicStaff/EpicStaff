/**
 * Wraps a value in single quotes for a POSIX shell (bash, zsh, sh).
 * Inside single quotes nothing is special except the quote itself, so each `'`
 * closes the string, adds an escaped quote and reopens it: `'` → `'\''`.
 */
function quoteForPosixShell(value: string): string {
    return `'${value.replaceAll("'", `'\\''`)}'`;
}

/**
 * Builds a bash cURL command that starts the flow. Variable values come from the
 * user, so they are quoted to stay data and never run as shell commands.
 */
export function buildCurlCommand(flowUuid: string, variables: Record<string, unknown>, apiUrl: string): string {
    const payload = JSON.stringify({ graph_uuid: flowUuid, variables }, null, 2);

    return `curl \\
  -H "Content-Type: application/json" \\
  -H "Accept: application/json" \\
  -X POST \\
  -d ${quoteForPosixShell(payload)} \\
  ${apiUrl}run-session/`;
}
