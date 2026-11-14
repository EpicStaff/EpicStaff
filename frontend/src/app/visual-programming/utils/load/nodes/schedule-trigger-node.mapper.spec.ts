import { rewriteLegacyOnceScheduleName } from './schedule-trigger-node.mapper';

describe('rewriteLegacyOnceScheduleName', () => {
    it.each([
        { name: 'Once on 01 Jul 2026 at 12:30', rewritten: 'Once on 01 Jul 2026 at 12-30' },
        { name: 'Once on 01 Jul 2026 at 12-30', rewritten: 'Once on 01 Jul 2026 at 12-30' },
        // A legacy uniqueness suffix is kept; the panel regenerates a clean name on the next edit.
        { name: 'Once on 01 Jul 2026 at 12:30 #2', rewritten: 'Once on 01 Jul 2026 at 12-30 #2' },
        { name: 'Nightly import', rewritten: 'Nightly import' },
    ])('rewrites "$name" to "$rewritten"', ({ name, rewritten }) => {
        expect(rewriteLegacyOnceScheduleName(name)).toBe(rewritten);
    });
});
