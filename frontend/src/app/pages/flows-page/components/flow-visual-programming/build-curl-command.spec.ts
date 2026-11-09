import { buildCurlCommand } from './build-curl-command';

/**
 * Reads one POSIX shell word made only of '...' parts and \' escapes, as bash would.
 * Throws on anything else, so a value that breaks out of the quotes fails the test.
 */
function readSingleQuotedWord(word: string): string {
    let result = '';
    let index = 0;
    while (index < word.length) {
        if (word.startsWith("\\'", index)) {
            result += "'";
            index += 2;
            continue;
        }
        if (word[index] !== "'") throw new Error(`Unquoted text at ${index}: ${word.slice(index)}`);
        const closing = word.indexOf("'", index + 1);
        if (closing === -1) throw new Error('Unterminated quote');
        result += word.slice(index + 1, closing);
        index = closing + 1;
    }
    return result;
}

function dataArgument(command: string): string {
    const start = command.indexOf('-d ') + 3;
    const end = command.lastIndexOf(' \\\n');
    return command.slice(start, end);
}

describe('buildCurlCommand', () => {
    const apiUrl = 'http://localhost/api/';

    it('keeps a variable that tries to break out of the quotes as plain data', () => {
        const variables = { name: "x' ; touch /tmp/pwned ; echo '", note: "it's $(whoami) `id`" };

        const command = buildCurlCommand('flow-uuid', variables, apiUrl);

        const payload = readSingleQuotedWord(dataArgument(command));
        expect(JSON.parse(payload)).toEqual({ graph_uuid: 'flow-uuid', variables });
    });

    it('writes DEL and every non-ASCII character as a JSON escape, so a terminal cannot read them as keys', () => {
        const variables = {
            ['key\u007f']: "a'\u007f; touch /tmp/pwned; #",
            other: 'b\u009b $(touch /tmp/pwned)\u2005',
            text: 'Київ 🚀',
        };

        const command = buildCurlCommand('flow-uuid', variables, apiUrl);

        expect(command).toMatch(/^[\x20-\x7e\n]*$/);
        const payload = readSingleQuotedWord(dataArgument(command));
        expect(JSON.parse(payload)).toEqual({ graph_uuid: 'flow-uuid', variables });
    });

    it('posts to the quoted run-session URL', () => {
        const command = buildCurlCommand('flow-uuid', {}, apiUrl);

        expect(command.endsWith(`'${apiUrl}run-session/'`)).toBe(true);
    });
});
