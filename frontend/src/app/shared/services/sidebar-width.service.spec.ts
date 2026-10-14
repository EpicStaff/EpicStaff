import { SidebarWidthOptions, SidebarWidthService } from './sidebar-width.service';

const KEY = 'test-sidebar';
const STORAGE_KEY = `sidebar-width:${KEY}`;

const COLLAPSIBLE: SidebarWidthOptions = {
    defaultWidth: 60,
    minWidth: 180,
    maxWidth: 320,
    collapse: { collapsedWidth: 60, collapseThreshold: 120 },
};

describe('SidebarWidthService', () => {
    let service: SidebarWidthService;

    beforeEach(() => {
        localStorage.clear();
        service = new SidebarWidthService();
    });

    afterEach(() => {
        localStorage.clear();
    });

    describe('without collapse options', () => {
        it('falls back to the built-in default width', () => {
            expect(service.getWidth(KEY)()).toBe(360);
        });

        it('clamps to the default bounds', () => {
            const width = service.getWidth(KEY);

            service.setWidth(KEY, 100);
            expect(width()).toBe(220);

            service.setWidth(KEY, 900);
            expect(width()).toBe(600);
        });

        it('rounds and keeps a width within the bounds', () => {
            const width = service.getWidth(KEY, { minWidth: 100, maxWidth: 400 });

            service.setWidth(KEY, 250.6, { minWidth: 100, maxWidth: 400 });

            expect(width()).toBe(251);
        });

        it('clamps a stored width to the bounds', () => {
            localStorage.setItem(STORAGE_KEY, '50');

            expect(service.getWidth(KEY)()).toBe(220);
        });
    });

    describe('with collapse options', () => {
        it('starts collapsed when nothing is stored', () => {
            expect(service.getWidth(KEY, COLLAPSIBLE)()).toBe(60);
        });

        it.each([
            [0, 60],
            [80, 60],
            [119, 60],
            [120, 180],
            [150, 180],
            [180, 180],
            [250, 250],
            [320, 320],
            [500, 320],
        ])('snaps a requested width of %ipx to %ipx', (requested, expected) => {
            const width = service.getWidth(KEY, COLLAPSIBLE);

            service.setWidth(KEY, requested, COLLAPSIBLE);

            expect(width()).toBe(expected);
        });

        it.each([
            ['100', 60],
            ['150', 180],
            ['240', 240],
            ['999', 320],
        ])('snaps a stored in-between width of %spx to %ipx', (stored, expected) => {
            localStorage.setItem(STORAGE_KEY, stored);

            expect(service.getWidth(KEY, COLLAPSIBLE)()).toBe(expected);
        });

        it('ignores a stored value that is not a number', () => {
            localStorage.setItem(STORAGE_KEY, 'wide');

            expect(service.getWidth(KEY, COLLAPSIBLE)()).toBe(60);
        });

        it('persists only the snapped width on commit', () => {
            service.getWidth(KEY, COLLAPSIBLE);

            service.setWidth(KEY, 140, COLLAPSIBLE);
            service.commitWidth(KEY);
            expect(localStorage.getItem(STORAGE_KEY)).toBe('180');

            service.setWidth(KEY, 90, COLLAPSIBLE);
            service.commitWidth(KEY);
            expect(localStorage.getItem(STORAGE_KEY)).toBe('60');
        });
    });

    it('restores a committed width in a fresh session', () => {
        service.getWidth(KEY, COLLAPSIBLE);
        service.setWidth(KEY, 260, COLLAPSIBLE);
        service.commitWidth(KEY);

        const nextSessionService = new SidebarWidthService();

        expect(nextSessionService.getWidth(KEY, COLLAPSIBLE)()).toBe(260);
    });

    it('does not persist before a width is committed', () => {
        service.getWidth(KEY, COLLAPSIBLE);
        service.setWidth(KEY, 260, COLLAPSIBLE);

        expect(localStorage.getItem(STORAGE_KEY)).toBeNull();
    });
});
