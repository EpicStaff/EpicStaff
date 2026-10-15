export type SnakeDirection = 'up' | 'down' | 'left' | 'right';

/** A cell on the snake grid; column 0 / row 0 is the top-left corner. */
export interface GridCell {
    column: number;
    row: number;
}

/** Outcome of a single engine tick. */
export type SnakeStepOutcome = 'moved' | 'ate' | 'died' | 'over';

export interface SnakeEngineConfig {
    columns: number;
    rows: number;
    initialLength: number;
    initialStepIntervalMs: number;
    minimumStepIntervalMs: number;
    speedUpPerFoodMs: number;
    pointsPerFood: number;
    /** Returns a number in [0, 1); injectable so food placement is deterministic in tests. */
    random: () => number;
}

export const DEFAULT_SNAKE_ENGINE_CONFIG: Omit<SnakeEngineConfig, 'columns' | 'rows' | 'random'> = {
    initialLength: 4,
    initialStepIntervalMs: 120,
    minimumStepIntervalMs: 55,
    speedUpPerFoodMs: 6,
    pointsPerFood: 10,
};

const DIRECTION_OFFSETS: Record<SnakeDirection, GridCell> = {
    up: { column: 0, row: -1 },
    down: { column: 0, row: 1 },
    left: { column: -1, row: 0 },
    right: { column: 1, row: 0 },
};

/** Maximum number of turns buffered ahead of the snake; one is consumed per tick. */
export const MAX_QUEUED_DIRECTIONS = 3;

const OPPOSITE_DIRECTIONS: Record<SnakeDirection, SnakeDirection> = {
    up: 'down',
    down: 'up',
    left: 'right',
    right: 'left',
};

/** Framework-free classic snake rules: grid movement, buffered turns, growth, collisions, speed-up and a play clock. */
export class SnakeEngine {
    private body: GridCell[];
    private currentDirection: SnakeDirection = 'right';
    private readonly queuedDirections: SnakeDirection[] = [];
    private foodCell: GridCell | null = null;
    private currentScore = 0;
    private eatenFoodCount = 0;
    private currentStepIntervalMs: number;
    private gameOver = false;
    private playElapsedMs = 0;

    constructor(private readonly config: SnakeEngineConfig) {
        if (config.columns < 2 || config.rows < 1) {
            throw new Error('Snake grid must be at least 2 columns by 1 row');
        }
        this.currentStepIntervalMs = config.initialStepIntervalMs;
        this.body = this.createInitialBody();
        this.foodCell = this.spawnFood();
    }

    get snake(): readonly GridCell[] {
        return this.body;
    }

    get food(): GridCell | null {
        return this.foodCell;
    }

    get direction(): SnakeDirection {
        return this.currentDirection;
    }

    get score(): number {
        return this.currentScore;
    }

    get foodEaten(): number {
        return this.eatenFoodCount;
    }

    get stepIntervalMs(): number {
        return this.currentStepIntervalMs;
    }

    get isGameOver(): boolean {
        return this.gameOver;
    }

    /** Time played so far; it stops counting when the snake crashes. */
    get elapsedMs(): number {
        return this.playElapsedMs;
    }

    get columns(): number {
        return this.config.columns;
    }

    get rows(): number {
        return this.config.rows;
    }

    /** Buffers a turn (up to `MAX_QUEUED_DIRECTIONS`); rejects duplicates and reversals of the last buffered direction. */
    queueDirection(direction: SnakeDirection): boolean {
        if (this.gameOver || this.queuedDirections.length >= MAX_QUEUED_DIRECTIONS) return false;
        const lastDirection = this.queuedDirections.at(-1) ?? this.currentDirection;
        if (direction === lastDirection || direction === OPPOSITE_DIRECTIONS[lastDirection]) return false;
        this.queuedDirections.push(direction);
        return true;
    }

    /** Adds play time to the clock; ignored once the game is over or for non-positive deltas. */
    advanceClock(deltaMs: number): void {
        if (this.gameOver || deltaMs <= 0) return;
        this.playElapsedMs += deltaMs;
    }

    /** Advances the snake one cell, resolving food, growth and collisions. */
    step(): SnakeStepOutcome {
        if (this.gameOver) return 'over';

        const nextDirection = this.queuedDirections.shift();
        if (nextDirection) this.currentDirection = nextDirection;

        const head = this.body[0];
        const offset = DIRECTION_OFFSETS[this.currentDirection];
        const nextHead: GridCell = { column: head.column + offset.column, row: head.row + offset.row };
        const willEat = this.foodCell !== null && isSameCell(nextHead, this.foodCell);
        const blockingBody = willEat ? this.body : this.body.slice(0, -1);

        if (!this.isInsideGrid(nextHead) || blockingBody.some((cell) => isSameCell(cell, nextHead))) {
            this.endGame();
            return 'died';
        }

        this.body = willEat ? [nextHead, ...this.body] : [nextHead, ...this.body.slice(0, -1)];
        if (!willEat) return 'moved';

        this.currentScore += this.config.pointsPerFood;
        this.eatenFoodCount += 1;
        this.currentStepIntervalMs = Math.max(
            this.config.minimumStepIntervalMs,
            this.currentStepIntervalMs - this.config.speedUpPerFoodMs
        );
        this.foodCell = this.spawnFood();
        return 'ate';
    }

    private endGame(): void {
        this.gameOver = true;
        this.queuedDirections.length = 0;
    }

    private createInitialBody(): GridCell[] {
        const length = Math.max(1, Math.min(this.config.initialLength, Math.floor(this.config.columns / 2)));
        const headColumn = Math.floor(this.config.columns / 2);
        const row = Math.floor(this.config.rows / 2);
        return Array.from({ length }, (_, index) => ({ column: headColumn - index, row }));
    }

    private spawnFood(): GridCell | null {
        const occupied = new Set(this.body.map((cell) => this.cellKey(cell)));
        const freeCells: GridCell[] = [];
        for (let row = 0; row < this.config.rows; row++) {
            for (let column = 0; column < this.config.columns; column++) {
                if (!occupied.has(this.cellKey({ column, row }))) freeCells.push({ column, row });
            }
        }
        if (freeCells.length === 0) return null;
        const index = Math.min(freeCells.length - 1, Math.floor(this.config.random() * freeCells.length));
        return freeCells[index];
    }

    private isInsideGrid(cell: GridCell): boolean {
        return cell.column >= 0 && cell.row >= 0 && cell.column < this.config.columns && cell.row < this.config.rows;
    }

    private cellKey(cell: GridCell): number {
        return cell.row * this.config.columns + cell.column;
    }
}

function isSameCell(first: GridCell, second: GridCell): boolean {
    return first.column === second.column && first.row === second.row;
}
