import { isSecretCodeLocked } from './secret-code-lock.util';

describe('isSecretCodeLocked', () => {
    it.each([
        ['locks code reading a secret for a user without Secrets:Use', [7], false, true],
        ['locks code reading several secrets for a user without Secrets:Use', [7, 8], false, true],
        ['leaves code reading a secret open to a user with Secrets:Use', [7], true, false],
        ['leaves code reading no secret open', [], false, false],
    ])('%s', (_case, secretIds, canUseSecrets, expected) => {
        expect(isSecretCodeLocked(secretIds, canUseSecrets)).toBe(expected);
    });
});
