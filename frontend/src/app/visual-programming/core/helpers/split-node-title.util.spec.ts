import { splitNodeTitleBadge } from './split-node-title.util';

describe('splitNodeTitleBadge', () => {
    it('returns the full name as label with no badge when nodeNumber is null', () => {
        expect(splitNodeTitleBadge('Agent-Node #3', null)).toEqual({ label: 'Agent-Node #3', badge: null });
    });

    it('returns the full name as label with no badge when nodeNumber is undefined', () => {
        expect(splitNodeTitleBadge('Agent-Node #3', undefined)).toEqual({ label: 'Agent-Node #3', badge: null });
    });

    it('splits the badge suffix from the name when the name ends with " #N"', () => {
        expect(splitNodeTitleBadge('Agent-Node #3', 3)).toEqual({ label: 'Agent-Node', badge: '#3' });
    });

    it('returns no badge when the name does not end with the expected suffix', () => {
        expect(splitNodeTitleBadge('Custom Name', 3)).toEqual({ label: 'Custom Name', badge: null });
    });

    it('handles multi-digit node numbers', () => {
        expect(splitNodeTitleBadge('Task-Node #42', 42)).toEqual({ label: 'Task-Node', badge: '#42' });
    });

    it('does not split when the badge appears mid-string', () => {
        expect(splitNodeTitleBadge('#5 Agent-Node', 5)).toEqual({ label: '#5 Agent-Node', badge: null });
    });
});
