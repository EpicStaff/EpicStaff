import { getUserInitials } from './user-initials.util';

describe('getUserInitials', () => {
    it('takes the first letters of the first two words', () => {
        expect(getUserInitials('Ivan Bohun')).toBe('IB');
        expect(getUserInitials('ivan petro bohun')).toBe('IP');
    });

    it('takes the first two letters of a single word', () => {
        expect(getUserInitials('olga')).toBe('OL');
        expect(getUserInitials('O')).toBe('O');
    });

    it('ignores surrounding and repeated whitespace', () => {
        expect(getUserInitials('  Ivan    Bohun  ')).toBe('IB');
    });

    it('is empty when there is no usable name, so the avatar falls back to a placeholder', () => {
        expect(getUserInitials(null)).toBe('');
        expect(getUserInitials('')).toBe('');
        expect(getUserInitials('   ')).toBe('');
    });
});
