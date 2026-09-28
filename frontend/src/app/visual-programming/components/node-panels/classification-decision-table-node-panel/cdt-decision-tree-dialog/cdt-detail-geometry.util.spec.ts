import { codeBlockHeight, isScrolledToEnd } from './cdt-detail-geometry.util';

describe('codeBlockHeight', () => {
    // Window 100..700, with the section's 24px bottom padding as the gap.
    const viewport = { viewportTop: 100, viewportHeight: 600, bottomGap: 24 };

    it('reaches from the block top to the gap above the window bottom', () => {
        expect(codeBlockHeight({ ...viewport, blockTop: 400 })).toBe(276);
    });

    it('with no gap, reaches the window bottom itself', () => {
        expect(codeBlockHeight({ ...viewport, bottomGap: 0, blockTop: 400 })).toBe(300);
    });

    it('grows by exactly what the window scrolled, as the block top rises', () => {
        const before = codeBlockHeight({ ...viewport, blockTop: 400 });
        const after = codeBlockHeight({ ...viewport, blockTop: 400 - 120 });

        expect(after - before).toBe(120);
    });

    it('fills the window less the gap once the block top reaches the window top', () => {
        expect(codeBlockHeight({ ...viewport, blockTop: 100 })).toBe(576);
    });

    it('is never negative', () => {
        expect(codeBlockHeight({ ...viewport, blockTop: 900 })).toBe(0);
    });
});

describe('isScrolledToEnd', () => {
    it('is false while the window can still scroll down', () => {
        expect(isScrolledToEnd({ scrollTop: 100, scrollHeight: 1000, clientHeight: 600 })).toBe(false);
    });

    it('is true at the end', () => {
        expect(isScrolledToEnd({ scrollTop: 400, scrollHeight: 1000, clientHeight: 600 })).toBe(true);
    });

    it('tolerates a sub-pixel shortfall of up to 1px', () => {
        expect(isScrolledToEnd({ scrollTop: 399.2, scrollHeight: 1000, clientHeight: 600 })).toBe(true);
        expect(isScrolledToEnd({ scrollTop: 398.5, scrollHeight: 1000, clientHeight: 600 })).toBe(false);
    });

    it('is true for a window with nothing to scroll', () => {
        expect(isScrolledToEnd({ scrollTop: 0, scrollHeight: 600, clientHeight: 600 })).toBe(true);
    });
});
