import { getClassificationDecisionTableVisualHeight } from './node-size.util';

describe('getClassificationDecisionTableVisualHeight', () => {
    it('reserves one placeholder row when there are no condition groups', () => {
        expect(getClassificationDecisionTableVisualHeight([])).toBe(60 + 46 * 3);
    });

    it('counts only groups that would actually render a row (valid, dock_visible, has a route_code)', () => {
        const groups = [
            { valid: true, dock_visible: true, route_code: 'A' },
            { valid: false, dock_visible: true, route_code: 'B' },
            { valid: true, dock_visible: false, route_code: 'C' },
            { valid: true, dock_visible: true, route_code: undefined },
            { valid: true, dock_visible: true, route_code: 'D' },
        ];

        expect(getClassificationDecisionTableVisualHeight(groups)).toBe(60 + 46 * 4);
    });

    it('grows linearly as more groups are added', () => {
        const groups = Array.from({ length: 6 }, (_, i) => ({
            valid: true,
            dock_visible: true,
            route_code: `route-${i}`,
        }));

        expect(getClassificationDecisionTableVisualHeight(groups)).toBe(60 + 46 * 8);
    });
});
