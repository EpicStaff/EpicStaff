import {
    DEFAULT_SNAKE_ENGINE_CONFIG,
    GridCell,
    MAX_QUEUED_DIRECTIONS,
    SnakeEngine,
    SnakeEngineConfig,
} from './snake-engine';

function createEngine(overrides: Partial<SnakeEngineConfig> = {}): SnakeEngine {
    return new SnakeEngine({
        ...DEFAULT_SNAKE_ENGINE_CONFIG,
        columns: 10,
        rows: 10,
        random: () => 0,
        ...overrides,
    });
}

/** Random source whose first draw places the food on `target`, given the cells occupied at spawn time. */
function randomPointingAt(
    columns: number,
    rows: number,
    occupied: readonly GridCell[],
    target: GridCell
): () => number {
    const occupiedKeys = new Set(occupied.map((cell) => cell.row * columns + cell.column));
    const targetKey = target.row * columns + target.column;
    let freeCellsBeforeTarget = 0;
    for (let key = 0; key < targetKey; key++) {
        if (!occupiedKeys.has(key)) freeCellsBeforeTarget++;
    }
    const freeCount = columns * rows - occupied.length;
    return () => (freeCellsBeforeTarget + 0.5) / freeCount;
}

describe('SnakeEngine', () => {
    it('starts centred, heading right, with the configured length', () => {
        const engine = createEngine();

        expect(engine.direction).toBe('right');
        expect(engine.snake).toEqual([
            { column: 5, row: 5 },
            { column: 4, row: 5 },
            { column: 3, row: 5 },
            { column: 2, row: 5 },
        ]);
    });

    it('moves the head one cell per step and keeps its length when not eating', () => {
        const engine = createEngine();

        expect(engine.step()).toBe('moved');
        expect(engine.snake[0]).toEqual({ column: 6, row: 5 });
        expect(engine.snake).toHaveLength(4);
    });

    it('applies a queued turn on the next step', () => {
        const engine = createEngine();

        expect(engine.queueDirection('up')).toBe(true);
        engine.step();

        expect(engine.direction).toBe('up');
        expect(engine.snake[0]).toEqual({ column: 5, row: 4 });
    });

    it('blocks a 180-degree reversal', () => {
        const engine = createEngine();

        expect(engine.queueDirection('left')).toBe(false);
        engine.step();

        expect(engine.direction).toBe('right');
        expect(engine.snake[0]).toEqual({ column: 6, row: 5 });
    });

    it('keeps a quick second turn and applies one queued turn per tick', () => {
        const engine = createEngine();

        expect(engine.queueDirection('up')).toBe(true);
        expect(engine.queueDirection('left')).toBe(true);

        engine.step();
        expect(engine.direction).toBe('up');
        expect(engine.snake[0]).toEqual({ column: 5, row: 4 });

        engine.step();
        expect(engine.direction).toBe('left');
        expect(engine.snake[0]).toEqual({ column: 4, row: 4 });
    });

    it('checks new turns against the last queued direction, not the current one', () => {
        const engine = createEngine();

        expect(engine.queueDirection('up')).toBe(true);
        expect(engine.queueDirection('up')).toBe(false);
        expect(engine.queueDirection('down')).toBe(false);
        // 'left' reverses the current direction but is a valid turn after the queued 'up'.
        expect(engine.queueDirection('left')).toBe(true);
    });

    it(`buffers at most ${MAX_QUEUED_DIRECTIONS} turns`, () => {
        const engine = createEngine();

        expect(engine.queueDirection('up')).toBe(true);
        expect(engine.queueDirection('left')).toBe(true);
        expect(engine.queueDirection('down')).toBe(true);
        expect(engine.queueDirection('right')).toBe(false);

        engine.step();
        expect(engine.queueDirection('right')).toBe(true);
    });

    it('grows, scores and speeds up when it eats', () => {
        const initialBody = createEngine().snake;
        const engine = createEngine({ random: randomPointingAt(10, 10, initialBody, { column: 6, row: 5 }) });
        expect(engine.food).toEqual({ column: 6, row: 5 });

        expect(engine.step()).toBe('ate');

        expect(engine.snake).toHaveLength(5);
        expect(engine.score).toBe(DEFAULT_SNAKE_ENGINE_CONFIG.pointsPerFood);
        expect(engine.foodEaten).toBe(1);
        expect(engine.stepIntervalMs).toBe(
            DEFAULT_SNAKE_ENGINE_CONFIG.initialStepIntervalMs - DEFAULT_SNAKE_ENGINE_CONFIG.speedUpPerFoodMs
        );
    });

    it('never speeds up past the minimum step interval', () => {
        // One-row board, snake of length 1 heading right from column 30: every spawn lands right in front of
        // the head, which is always the 31st free cell (index 30) in row-major order.
        let spawnCount = 0;
        const columns = 60;
        const engine = createEngine({
            columns,
            rows: 1,
            initialLength: 1,
            random: () => (30 + 0.5) / (columns - 1 - spawnCount++),
        });

        for (let bite = 0; bite < 25; bite++) {
            expect(engine.step()).toBe('ate');
        }

        expect(engine.foodEaten).toBe(25);
        expect(engine.stepIntervalMs).toBe(DEFAULT_SNAKE_ENGINE_CONFIG.minimumStepIntervalMs);
    });

    it('dies when it hits a wall', () => {
        const engine = createEngine({ random: () => 0.999 });

        let outcome = engine.step();
        while (outcome === 'moved' || outcome === 'ate') outcome = engine.step();

        expect(outcome).toBe('died');
        expect(engine.isGameOver).toBe(true);
        expect(engine.snake[0].column).toBe(9);
        expect(engine.step()).toBe('over');
    });

    it('dies when it runs into its own body', () => {
        const engine = createEngine({ initialLength: 5, random: () => 0 });

        engine.queueDirection('up');
        engine.step();
        engine.queueDirection('left');
        engine.step();
        engine.queueDirection('down');

        expect(engine.step()).toBe('died');
        expect(engine.isGameOver).toBe(true);
    });

    it('allows moving into the cell the tail is leaving', () => {
        const engine = createEngine({ initialLength: 4, random: () => 0 });

        engine.queueDirection('up');
        engine.step();
        engine.queueDirection('left');
        engine.step();
        engine.queueDirection('down');
        // Body is now (4,4) (5,4) (5,5) (4,5); moving down enters (4,5) exactly as the tail leaves it.
        expect(engine.step()).toBe('moved');
    });

    it('never spawns food on the snake', () => {
        for (const randomValue of [0, 0.1, 0.25, 0.5, 0.75, 0.9, 0.999999]) {
            const engine = createEngine({ columns: 6, rows: 2, initialLength: 3, random: () => randomValue });
            const food = engine.food!;

            expect(engine.snake.some((cell) => cell.column === food.column && cell.row === food.row)).toBe(false);
        }
    });

    it('uses the tense speed ramp: 120ms start, 6ms per bite, 55ms floor', () => {
        expect(DEFAULT_SNAKE_ENGINE_CONFIG.initialStepIntervalMs).toBe(120);
        expect(DEFAULT_SNAKE_ENGINE_CONFIG.speedUpPerFoodMs).toBe(6);
        expect(DEFAULT_SNAKE_ENGINE_CONFIG.minimumStepIntervalMs).toBe(55);
    });

    describe('play clock', () => {
        it('counts up while playing', () => {
            const engine = createEngine();

            engine.advanceClock(1500);
            engine.advanceClock(500);

            expect(engine.elapsedMs).toBe(2000);
        });

        it('stops counting once the snake has crashed', () => {
            const engine = createEngine({ random: () => 0.999 });
            while (engine.step() !== 'died') {
                engine.advanceClock(100);
            }
            const elapsedAtCrash = engine.elapsedMs;

            engine.advanceClock(5000);

            expect(engine.isGameOver).toBe(true);
            expect(engine.elapsedMs).toBe(elapsedAtCrash);
        });

        it('ignores non-positive deltas', () => {
            const engine = createEngine();

            engine.advanceClock(0);
            engine.advanceClock(-100);

            expect(engine.elapsedMs).toBe(0);
        });
    });

    it('rejects grids that are too small to play on', () => {
        expect(() => createEngine({ columns: 1, rows: 1 })).toThrow();
    });
});
