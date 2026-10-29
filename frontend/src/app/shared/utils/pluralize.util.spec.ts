import { pluralize } from './pluralize.util';

describe('pluralize', () => {
    it.each([
        [0, '0 resources'],
        [1, '1 resource'],
        [2, '2 resources'],
    ])('%i → %s', (count, expected) => {
        expect(pluralize(count, 'resource', 'resources')).toBe(expected);
    });
});
