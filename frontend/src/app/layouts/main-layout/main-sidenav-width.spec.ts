import { SidebarWidthService } from '@shared/services';

import {
    isMainSidenavExpanded,
    MAIN_SIDENAV_COLLAPSED_WIDTH,
    MAIN_SIDENAV_WIDTH_KEY,
    MAIN_SIDENAV_WIDTH_OPTIONS,
} from './main-sidenav-width';

describe('main sidenav width', () => {
    const { minWidth, maxWidth, collapse } = MAIN_SIDENAV_WIDTH_OPTIONS;

    beforeEach(() => localStorage.clear());
    afterEach(() => localStorage.clear());

    it('keeps the collapse threshold between the collapsed and the minimum expanded width', () => {
        expect(collapse.collapsedWidth).toBe(MAIN_SIDENAV_COLLAPSED_WIDTH);
        expect(collapse.collapseThreshold).toBeGreaterThan(collapse.collapsedWidth);
        expect(collapse.collapseThreshold).toBeLessThanOrEqual(minWidth);
        expect(minWidth).toBeLessThan(maxWidth);
    });

    it('derives the expanded state from the width alone', () => {
        expect(isMainSidenavExpanded(MAIN_SIDENAV_COLLAPSED_WIDTH)).toBe(false);
        expect(isMainSidenavExpanded(minWidth)).toBe(true);
        expect(isMainSidenavExpanded(maxWidth)).toBe(true);
    });

    it('never lands between the collapsed and the minimum expanded width', () => {
        const service = new SidebarWidthService();
        const width = service.getWidth(MAIN_SIDENAV_WIDTH_KEY, MAIN_SIDENAV_WIDTH_OPTIONS);

        for (let requested = 0; requested <= maxWidth + 50; requested++) {
            service.setWidth(MAIN_SIDENAV_WIDTH_KEY, requested, MAIN_SIDENAV_WIDTH_OPTIONS);
            const isCollapsed = width() === MAIN_SIDENAV_COLLAPSED_WIDTH;
            const isWithinExpandedRange = width() >= minWidth && width() <= maxWidth;
            expect(isCollapsed || isWithinExpandedRange).toBe(true);
        }
    });
});
