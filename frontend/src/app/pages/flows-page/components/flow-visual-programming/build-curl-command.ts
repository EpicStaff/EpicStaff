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
 *
 * The URL is resolved against `origin`, because the app's API URL is usually a
 * relative path, which works in the browser but gives curl no host to call.
 * Both credential headers are placeholders for the user to fill in: the server
 * checks a Bearer token before an API key and rejects an invalid one outright,
 * so the command must be run with only one of them (the copy toast says so).
 */
export function buildCurlCommand(
    flowUuid: string,
    variables: Record<string, unknown>,
    apiUrl: string,
    origin: string
): string {
    const payload = JSON.stringify({ graph_uuid: flowUuid, variables }, null, 2);
    const runSessionUrl = new URL(`${apiUrl}run-session/`, origin).href;

    return `curl \\
  -H "Content-Type: application/json" \\
  -H "Accept: application/json" \\
  -H "Authorization: Bearer <YOUR_ACCESS_TOKEN>" \\
  -H "X-Api-Key: <YOUR_API_KEY>" \\
  -X POST \\
  -d ${quoteForPosixShell(payload)} \\
  ${runSessionUrl}`;
}
