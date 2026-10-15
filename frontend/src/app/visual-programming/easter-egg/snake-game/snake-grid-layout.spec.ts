import {
    chooseGridDimensions,
    computeGridLayout,
    GridArea,
    MINIMUM_COLUMNS,
    MINIMUM_ROWS,
    PREFERRED_CELL_SIZE_PX,
} from './snake-grid-layout';

function expectFits(area: GridArea): void {
    const dimensions = chooseGridDimensions(area);
    const layout = computeGridLayout(area, dimensions);

    expect(layout.originX).toBeGreaterThanOrEqual(area.left);
    expect(layout.originY).toBeGreaterThanOrEqual(area.top);
    expect(layout.originX + dimensions.columns * layout.cellSize).toBeLessThanOrEqual(area.left + area.width + 1);
    expect(layout.originY + dimensions.rows * layout.cellSize).toBeLessThanOrEqual(area.top + area.height + 1);
}

describe('snake grid layout', () => {
    it('gives a typical board about 30x18 cells at the preferred size', () => {
        const area: GridArea = { left: 16, top: 80, width: 1168, height: 704 };

        const dimensions = chooseGridDimensions(area);
        const layout = computeGridLayout(area, dimensions);

        expect(dimensions).toEqual({ columns: 30, rows: 18 });
        expect(layout.cellSize).toBe(PREFERRED_CELL_SIZE_PX);
    });

    it('centres the grid in the area', () => {
        const area: GridArea = { left: 0, top: 0, width: 400, height: 300 };

        const layout = computeGridLayout(area, { columns: 10, rows: 5 });

        expect(layout.cellSize).toBe(40);
        expect(layout.originX).toBe(0);
        expect(layout.originY).toBe(50);
    });

    it('keeps the playable minimum on small boards', () => {
        expect(chooseGridDimensions({ left: 0, top: 0, width: 100, height: 60 })).toEqual({
            columns: MINIMUM_COLUMNS,
            rows: MINIMUM_ROWS,
        });
    });

    it.each([
        { left: 16, top: 80, width: 1168, height: 704 },
        { left: 16, top: 80, width: 1168, height: 60 },
        { left: 16, top: 80, width: 50, height: 704 },
        { left: 16, top: 80, width: 40, height: 30 },
        { left: 16, top: 80, width: 301, height: 227 },
    ])('always fits the grid inside %o', (area) => {
        expectFits(area);
    });

    it('shrinks cells instead of overflowing on a very short board', () => {
        const area: GridArea = { left: 0, top: 0, width: 1000, height: 60 };

        const dimensions = chooseGridDimensions(area);
        const layout = computeGridLayout(area, dimensions);

        expect(dimensions.rows).toBe(MINIMUM_ROWS);
        expect(layout.cellSize).toBe(10);
        expect(dimensions.rows * layout.cellSize).toBeLessThanOrEqual(area.height);
    });
});
