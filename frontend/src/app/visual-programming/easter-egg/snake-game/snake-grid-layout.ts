/** Where the snake grid sits on the board, in overlay-local CSS pixels. */
export interface GridLayout {
    cellSize: number;
    originX: number;
    originY: number;
}

/** The rectangle the grid must fit in. */
export interface GridArea {
    left: number;
    top: number;
    width: number;
    height: number;
}

export interface GridDimensions {
    columns: number;
    rows: number;
}

export const PREFERRED_CELL_SIZE_PX = 38;
export const MINIMUM_COLUMNS = 8;
export const MINIMUM_ROWS = 6;

/** Picks how many cells fit at the preferred size, never fewer than the playable minimum. */
export function chooseGridDimensions(area: GridArea): GridDimensions {
    return {
        columns: Math.max(MINIMUM_COLUMNS, Math.floor(area.width / PREFERRED_CELL_SIZE_PX)),
        rows: Math.max(MINIMUM_ROWS, Math.floor(area.height / PREFERRED_CELL_SIZE_PX)),
    };
}

/** Sizes cells so the whole grid fits inside `area` and centres it; cells shrink below the preferred size when needed. */
export function computeGridLayout(area: GridArea, dimensions: GridDimensions): GridLayout {
    const fittingCellSize = Math.floor(Math.min(area.width / dimensions.columns, area.height / dimensions.rows));
    // A 1px cell is the smallest drawable size; it only overflows when the area has less than 1px per cell.
    const cellSize = Math.max(1, fittingCellSize);
    return {
        cellSize,
        originX: Math.round(area.left + (area.width - dimensions.columns * cellSize) / 2),
        originY: Math.round(area.top + (area.height - dimensions.rows * cellSize) / 2),
    };
}
