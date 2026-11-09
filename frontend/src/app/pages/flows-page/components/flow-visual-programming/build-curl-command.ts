/**
 * Wraps a value in single quotes for a POSIX shell (bash, zsh, sh).
 * Inside single quotes nothing is special except the quote itself, so each `'`
 * closes the string, adds an escaped quote and reopens it: `'` → `'\''`.
 */
function quoteForPosixShell(value: string): string {
    return `'${value.replaceAll("'", `'\\''`)}'`;
}

/**
 * Keeps the payload pure ASCII by writing DEL and every non-ASCII character as a
 * `\uXXXX` escape. A terminal that edits pasted input can read those bytes as
 * key presses: DEL erases a character (maybe a closing quote), and in a non-UTF-8
 * bash each byte above 0x7F is a Meta key that can expand `$(...)` on the line.
 * The JSON keeps the same meaning.
 */
function escapeNonAsciiCharacters(json: string): string {
    return json.replace(/[^ -~\n]/g, (character) => `\\u${character.charCodeAt(0).toString(16).padStart(4, '0')}`);
}

/**
 * Builds a bash cURL command that starts the flow. Variable values come from the
 * user, so they are quoted to stay data and never run as shell commands.
 */
export function buildCurlCommand(flowUuid: string, variables: Record<string, unknown>, apiUrl: string): string {
    const payload = escapeNonAsciiCharacters(JSON.stringify({ graph_uuid: flowUuid, variables }, null, 2));

    return `curl \\
  -H "Content-Type: application/json" \\
  -H "Accept: application/json" \\
  -X POST \\
  -d ${quoteForPosixShell(payload)} \\
  ${quoteForPosixShell(`${apiUrl}run-session/`)}`;
}
