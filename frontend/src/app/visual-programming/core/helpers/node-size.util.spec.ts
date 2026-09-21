import { DT_MIN_HEIGHT, getClassificationTableVisualHeight, getDecisionTableVisualHeight } from './node-size.util';

describe('getDecisionTableVisualHeight', () => {
    it('reserves one placeholder row when there are no condition groups', () => {
        expect(getDecisionTableVisualHeight([])).toBe(60 + 60 * 3);
    });

    it('counts N valid groups as header + row * (N + 2)', () => {
        const groups = [{ valid: true }, { valid: true }, { valid: true }];
        expect(getDecisionTableVisualHeight(groups)).toBe(60 + 60 * (3 + 2));
    });

    it('excludes groups explicitly marked invalid', () => {
        const groups = [{ valid: true }, { valid: false }, { valid: true }];
        expect(getDecisionTableVisualHeight(groups)).toBe(60 + 60 * (2 + 2));
    });

    it('never drops below DT_MIN_HEIGHT', () => {
        expect(getDecisionTableVisualHeight([])).toBe(DT_MIN_HEIGHT);
    });
});

describe('getClassificationTableVisualHeight', () => {
    it('reserves one placeholder row when there are no condition groups', () => {
        expect(getClassificationTableVisualHeight([])).toBe(60 + 60 * 3);
    });

    it('counts only groups that would actually render a row (valid, dock_visible, has a route_code)', () => {
        const groups = [
            { valid: true, dock_visible: true, route_code: 'A' },
            { valid: false, dock_visible: true, route_code: 'B' },
            { valid: true, dock_visible: false, route_code: 'C' },
            { valid: true, dock_visible: true, route_code: undefined },
            { valid: true, dock_visible: true, route_code: 'D' },
        ];

        expect(getClassificationTableVisualHeight(groups)).toBe(60 + 60 * 4);
    });

    it('grows linearly as more groups are added', () => {
        const groups = Array.from({ length: 6 }, (_, i) => ({
            valid: true,
            dock_visible: true,
            route_code: `route-${i}`,
        }));

        expect(getClassificationTableVisualHeight(groups)).toBe(60 + 60 * 8);
    });
});
