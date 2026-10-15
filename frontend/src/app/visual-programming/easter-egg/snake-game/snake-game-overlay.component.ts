import { DOCUMENT } from '@angular/common';
import {
    afterNextRender,
    Component,
    computed,
    DestroyRef,
    ElementRef,
    inject,
    input,
    NgZone,
    output,
    Renderer2,
    RendererStyleFlags2,
    signal,
    viewChild,
} from '@angular/core';

import { captureBoardNodes } from './board-snapshot';
import {
    BoardNodeSnapshot,
    buildExplosionParticles,
    DEFAULT_EXPLOSION_BUILD_OPTIONS,
    DEFAULT_EXPLOSION_STEP_OPTIONS,
    explosionDurationMs,
    ExplosionParticle,
    hasExplosionStarted,
    isExplosionFinished,
    stepExplosionParticles,
} from './pixel-explosion';
import { DEFAULT_SNAKE_ENGINE_CONFIG, SnakeDirection, SnakeEngine } from './snake-engine';
import { chooseGridDimensions, computeGridLayout, GridArea, GridLayout } from './snake-grid-layout';

type GamePhase = 'explosion' | 'playing' | 'over' | 'exiting';

interface GamePalette {
    boardTint: string;
    gridLine: string;
    boardFrame: string;
    snakeBody: string;
    snakeHead: string;
    deathFlash: string;
    nodeFallbackColor: string;
}

/** Hides the real nodes while the overlay paints them; defined in this component's stylesheet. */
const BOARD_HIDDEN_CLASS = 'snake-game-board-hidden';
/** Fades the real connections and minimap out once the nodes explode. */
const BOARD_EXPLODED_CLASS = 'snake-game-board-exploded';
/** Fades the real nodes and connections back in while the overlay fades out. */
const BOARD_RESTORING_CLASS = 'snake-game-board-restoring';
const FOOD_IMAGE_SOURCE = 'assets/icons/llm-providers-logos/logo.svg';

const BOARD_PADDING_PX = 16;
const HUD_RESERVED_HEIGHT_PX = 80;
/** Cells smaller than this are drawn without the 1px gap between snake segments. */
const SEGMENT_GAP_MIN_CELL_PX = 8;
const BOARD_TINT_ALPHA = 0.55;
const GRID_LINE_ALPHA = 0.6;

const MAX_FRAME_DELTA_MS = 100;
const TINT_FADE_DURATION_MS = 1000;
/** Guard only: the intro normally ends once the particles settle and the tint has faded in (well under 2s). */
const MAXIMUM_INTRO_MS = Math.max(
    explosionDurationMs(DEFAULT_EXPLOSION_BUILD_OPTIONS, DEFAULT_EXPLOSION_STEP_OPTIONS),
    DEFAULT_EXPLOSION_STEP_OPTIONS.holdDurationMs + TINT_FADE_DURATION_MS
);
const EXIT_FADE_MS = 250;

const DIRECTION_BY_KEY_CODE: Readonly<Record<string, SnakeDirection>> = {
    ArrowUp: 'up',
    KeyW: 'up',
    ArrowDown: 'down',
    KeyS: 'down',
    ArrowLeft: 'left',
    KeyA: 'left',
    ArrowRight: 'right',
    KeyD: 'right',
};

/** Full-board canvas overlay that explodes the visible nodes into pixels and then runs a timed snake round on the empty board. */
@Component({
    selector: 'app-snake-game-overlay',
    templateUrl: './snake-game-overlay.component.html',
    styleUrl: './snake-game-overlay.component.scss',
    host: {
        tabindex: '-1',
        '[class.is-exiting]': "phase() === 'exiting'",
        '(click)': 'onOverlayClick()',
        '(contextmenu)': '$event.preventDefault()',
    },
})
export class SnakeGameOverlayComponent {
    // Inputs / Outputs
    readonly boardElement = input.required<HTMLElement>();
    /** Node-type colour per node id, read from the flow models by the page. */
    readonly nodeColors = input<ReadonlyMap<string, string>>(new Map());
    readonly closed = output<void>();

    // View queries
    private readonly canvasRef = viewChild.required<ElementRef<HTMLCanvasElement>>('gameCanvas');

    // Signals & computed
    protected readonly phase = signal<GamePhase>('explosion');
    protected readonly score = signal(0);
    protected readonly foodEaten = signal(0);
    protected readonly elapsedSeconds = signal(0);
    protected readonly isGameOverCardVisible = signal(false);
    protected readonly isHudVisible = computed(() => this.phase() !== 'explosion');
    protected readonly elapsedLabel = computed(() => formatClock(this.elapsedSeconds()));

    // Private fields
    private readonly hostRef = inject<ElementRef<HTMLElement>>(ElementRef);
    private readonly ngZone = inject(NgZone);
    private readonly renderer = inject(Renderer2);
    private readonly document = inject(DOCUMENT);
    private readonly foodImage = new Image();
    private readonly keyDownListener = (event: KeyboardEvent): void => this.handleKeyDown(event);
    private readonly keyUpListener = (event: KeyboardEvent): void => handleKeyUp(event);

    private board: HTMLElement | null = null;
    private context: CanvasRenderingContext2D | null = null;
    private palette: GamePalette | null = null;
    private engine: SnakeEngine | null = null;
    private nodeSnapshots: BoardNodeSnapshot[] = [];
    private particles: ExplosionParticle[] = [];
    private boardWidth = 0;
    private boardHeight = 0;
    private introElapsedMs = 0;
    private isExploded = false;
    private appliedCellSize = 0;
    private stepAccumulatorMs = 0;
    private lastFrameTimestamp: number | null = null;
    private animationFrameId: number | null = null;
    private exitTimeoutId: ReturnType<typeof setTimeout> | null = null;
    private resizeObserver: ResizeObserver | null = null;

    constructor() {
        afterNextRender(() => this.start());
        inject(DestroyRef).onDestroy(() => this.teardown());
    }

    // Public methods
    protected onOverlayClick(): void {
        if (this.phase() === 'over') this.requestExit();
    }

    // Private methods
    private start(): void {
        const board = this.boardElement();
        const canvas = this.canvasRef().nativeElement;
        this.board = board;
        this.context = canvas.getContext('2d');
        this.palette = this.resolvePalette();
        this.syncGeometry();

        this.nodeSnapshots = captureBoardNodes(board, this.nodeColors(), this.palette.nodeFallbackColor);
        this.particles = buildExplosionParticles(this.nodeSnapshots, {
            ...DEFAULT_EXPLOSION_BUILD_OPTIONS,
            random: Math.random,
        });

        this.moveFocusToOverlay();
        this.renderIntro();
        this.renderer.addClass(board, BOARD_HIDDEN_CLASS);
        // Blocks pointer, focus and keyboard activation inside the board even if something slips past the overlay.
        this.renderer.setAttribute(board, 'inert', '');
        this.foodImage.src = FOOD_IMAGE_SOURCE;

        this.ngZone.runOutsideAngular(() => {
            window.addEventListener('keydown', this.keyDownListener, { capture: true });
            window.addEventListener('keyup', this.keyUpListener, { capture: true });
            this.resizeObserver = new ResizeObserver(() => this.handleResize());
            this.resizeObserver.observe(board);
            this.requestFrame();
        });
    }

    private teardown(): void {
        if (this.animationFrameId !== null) cancelAnimationFrame(this.animationFrameId);
        if (this.exitTimeoutId !== null) clearTimeout(this.exitTimeoutId);
        this.animationFrameId = null;
        this.exitTimeoutId = null;
        window.removeEventListener('keydown', this.keyDownListener, { capture: true });
        window.removeEventListener('keyup', this.keyUpListener, { capture: true });
        this.resizeObserver?.disconnect();
        this.resizeObserver = null;
        if (this.board) {
            this.renderer.removeClass(this.board, BOARD_HIDDEN_CLASS);
            this.renderer.removeClass(this.board, BOARD_EXPLODED_CLASS);
            this.renderer.removeClass(this.board, BOARD_RESTORING_CLASS);
            this.renderer.removeAttribute(this.board, 'inert');
        }
        this.board = null;
        this.engine = null;
        this.nodeSnapshots = [];
        this.particles = [];
    }

    private requestFrame(): void {
        this.animationFrameId = requestAnimationFrame((timestamp) => this.handleFrame(timestamp));
    }

    private handleFrame(timestamp: number): void {
        this.animationFrameId = null;
        const deltaMs =
            this.lastFrameTimestamp === null ? 0 : Math.min(MAX_FRAME_DELTA_MS, timestamp - this.lastFrameTimestamp);
        this.lastFrameTimestamp = timestamp;

        if (this.phase() === 'explosion') this.advanceIntro(deltaMs);
        else if (this.phase() === 'playing') this.advanceGame(deltaMs);

        const phase = this.phase();
        if (phase === 'explosion' || phase === 'playing') this.requestFrame();
    }

    private advanceIntro(deltaMs: number): void {
        this.introElapsedMs += deltaMs;
        if (!this.isExploded && hasExplosionStarted(this.introElapsedMs, DEFAULT_EXPLOSION_STEP_OPTIONS)) {
            this.isExploded = true;
            if (this.board) this.renderer.addClass(this.board, BOARD_EXPLODED_CLASS);
        }
        stepExplosionParticles(this.particles, this.introElapsedMs, deltaMs, {
            ...DEFAULT_EXPLOSION_STEP_OPTIONS,
            boardWidth: this.boardWidth,
            boardHeight: this.boardHeight,
        });
        this.renderIntro();

        const explosionElapsedMs = this.introElapsedMs - DEFAULT_EXPLOSION_STEP_OPTIONS.holdDurationMs;
        // Waiting for the tint keeps it from jumping to full strength when the particles clear early (or there are none).
        const isSettled =
            this.isExploded && isExplosionFinished(this.particles) && explosionElapsedMs >= TINT_FADE_DURATION_MS;
        if (isSettled || this.introElapsedMs >= MAXIMUM_INTRO_MS) this.startGame();
    }

    private startGame(): void {
        this.engine = new SnakeEngine({
            ...DEFAULT_SNAKE_ENGINE_CONFIG,
            ...chooseGridDimensions(this.gridArea()),
            random: Math.random,
        });
        this.nodeSnapshots = [];
        this.particles = [];
        this.ngZone.run(() => this.phase.set('playing'));
        this.renderGame();
    }

    private advanceGame(deltaMs: number): void {
        const engine = this.engine;
        if (!engine) return;
        engine.advanceClock(deltaMs);
        this.stepAccumulatorMs += deltaMs;

        // Frames are capped at MAX_FRAME_DELTA_MS, so this runs at most two steps per frame at top speed.
        while (!engine.isGameOver && this.stepAccumulatorMs >= engine.stepIntervalMs) {
            this.stepAccumulatorMs -= engine.stepIntervalMs;
            engine.step();
        }

        this.publishHud(engine);
        if (engine.isGameOver) this.finishGame();
        this.renderGame();
    }

    private publishHud(engine: SnakeEngine): void {
        const seconds = Math.floor(engine.elapsedMs / 1000);
        if (
            engine.score === this.score() &&
            engine.foodEaten === this.foodEaten() &&
            seconds === this.elapsedSeconds()
        ) {
            return;
        }
        this.ngZone.run(() => {
            this.score.set(engine.score);
            this.foodEaten.set(engine.foodEaten);
            this.elapsedSeconds.set(seconds);
        });
    }

    private finishGame(): void {
        this.ngZone.run(() => {
            this.isGameOverCardVisible.set(true);
            this.phase.set('over');
        });
    }

    private requestExit(): void {
        if (this.phase() === 'exiting' || !this.board) return;
        if (this.animationFrameId !== null) cancelAnimationFrame(this.animationFrameId);
        this.animationFrameId = null;
        this.ngZone.run(() => this.phase.set('exiting'));
        this.renderer.addClass(this.board, BOARD_RESTORING_CLASS);
        this.renderer.removeClass(this.board, BOARD_HIDDEN_CLASS);
        this.renderer.removeClass(this.board, BOARD_EXPLODED_CLASS);
        this.renderer.removeAttribute(this.board, 'inert');
        this.exitTimeoutId = setTimeout(() => {
            this.exitTimeoutId = null;
            this.ngZone.run(() => this.closed.emit());
        }, EXIT_FADE_MS);
    }

    private handleKeyDown(event: KeyboardEvent): void {
        swallowKeyEvent(event);
        if (event.key === 'Escape') {
            event.preventDefault();
            this.requestExit();
            return;
        }

        const hasModifier = event.ctrlKey || event.metaKey || event.altKey;
        // Cancelling Tab keeps focus on the overlay; cancelling Enter/Space/typing stops activating or editing anything
        // outside the board. Function keys and modified keys keep their browser defaults (F5, F12, Ctrl+R…).
        const mustCancel =
            !isFunctionKey(event) && (!hasModifier || isActivationKey(event) || isEditableTarget(event.target));
        if (mustCancel) event.preventDefault();

        const direction = hasModifier ? undefined : DIRECTION_BY_KEY_CODE[event.code];
        if (direction && this.phase() === 'playing') this.engine?.queueDirection(direction);
    }

    private handleResize(): void {
        this.syncGeometry();
        const phase = this.phase();
        if (phase === 'playing' || phase === 'over') this.renderGame();
    }

    /** Positions the host exactly over the board and sizes the canvas backing store for the device pixel ratio. */
    private syncGeometry(): void {
        const board = this.board;
        const host = this.hostRef.nativeElement;
        const canvas = this.canvasRef().nativeElement;
        if (!board) return;

        const boardRect = board.getBoundingClientRect();
        const offsetParent = (host.offsetParent as HTMLElement | null) ?? host.parentElement;
        const parentRect = offsetParent?.getBoundingClientRect();
        this.renderer.setStyle(host, 'left', `${boardRect.left - (parentRect?.left ?? 0)}px`);
        this.renderer.setStyle(host, 'top', `${boardRect.top - (parentRect?.top ?? 0)}px`);
        this.renderer.setStyle(host, 'width', `${boardRect.width}px`);
        this.renderer.setStyle(host, 'height', `${boardRect.height}px`);

        const devicePixelRatio = window.devicePixelRatio || 1;
        this.boardWidth = boardRect.width;
        this.boardHeight = boardRect.height;
        canvas.width = Math.max(1, Math.round(boardRect.width * devicePixelRatio));
        canvas.height = Math.max(1, Math.round(boardRect.height * devicePixelRatio));
        this.context?.setTransform(devicePixelRatio, 0, 0, devicePixelRatio, 0, 0);
        if (this.context) this.context.imageSmoothingEnabled = false;
    }

    /** Paints each node as one solid rounded block during the hold, then the flying particles. */
    private renderIntro(): void {
        const context = this.context;
        const palette = this.palette;
        if (!context || !palette) return;

        context.clearRect(0, 0, this.boardWidth, this.boardHeight);
        const explosionElapsedMs = this.introElapsedMs - DEFAULT_EXPLOSION_STEP_OPTIONS.holdDurationMs;
        const tintProgress = Math.min(1, Math.max(0, explosionElapsedMs / TINT_FADE_DURATION_MS));
        this.fillBoardTint(context, palette, tintProgress * BOARD_TINT_ALPHA);

        if (!this.isExploded) {
            for (const node of this.nodeSnapshots) {
                context.fillStyle = node.color;
                context.beginPath();
                context.roundRect(node.rect.left, node.rect.top, node.rect.width, node.rect.height, node.cornerRadius);
                context.fill();
            }
            return;
        }

        let activeColor = '';
        for (const particle of this.particles) {
            if (particle.alpha <= 0) continue;
            if (particle.color !== activeColor) {
                activeColor = particle.color;
                context.fillStyle = activeColor;
            }
            context.globalAlpha = particle.alpha;
            context.fillRect(Math.round(particle.x), Math.round(particle.y), particle.size, particle.size);
        }
        context.globalAlpha = 1;
    }

    private renderGame(): void {
        const context = this.context;
        const palette = this.palette;
        const engine = this.engine;
        if (!context || !palette || !engine) return;

        context.clearRect(0, 0, this.boardWidth, this.boardHeight);
        this.fillBoardTint(context, palette, BOARD_TINT_ALPHA);

        const layout = computeGridLayout(this.gridArea(), engine);
        this.applyCellSizeVariable(layout.cellSize);
        const gridWidth = engine.columns * layout.cellSize;
        const gridHeight = engine.rows * layout.cellSize;
        this.drawGridLines(context, palette, layout, engine);
        context.strokeStyle = palette.boardFrame;
        context.lineWidth = 2;
        context.strokeRect(layout.originX - 1, layout.originY - 1, gridWidth + 2, gridHeight + 2);

        const food = engine.food;
        if (food) {
            const inset = Math.max(1, Math.floor(layout.cellSize * 0.05));
            const foodX = layout.originX + food.column * layout.cellSize + inset;
            const foodY = layout.originY + food.row * layout.cellSize + inset;
            const foodSize = Math.max(1, layout.cellSize - inset * 2);
            if (this.foodImage.complete && this.foodImage.naturalWidth > 0) {
                context.drawImage(this.foodImage, foodX, foodY, foodSize, foodSize);
            } else {
                context.fillStyle = palette.snakeHead;
                context.fillRect(foodX, foodY, foodSize, foodSize);
            }
        }

        const segmentGap = layout.cellSize >= SEGMENT_GAP_MIN_CELL_PX ? 1 : 0;
        const headColor = engine.isGameOver ? palette.deathFlash : palette.snakeHead;
        engine.snake.forEach((segment, index) => {
            context.fillStyle = index === 0 ? headColor : palette.snakeBody;
            context.fillRect(
                layout.originX + segment.column * layout.cellSize + segmentGap,
                layout.originY + segment.row * layout.cellSize + segmentGap,
                layout.cellSize - segmentGap * 2,
                layout.cellSize - segmentGap * 2
            );
        });
    }

    private drawGridLines(
        context: CanvasRenderingContext2D,
        palette: GamePalette,
        layout: GridLayout,
        engine: SnakeEngine
    ): void {
        const gridWidth = engine.columns * layout.cellSize;
        const gridHeight = engine.rows * layout.cellSize;
        context.globalAlpha = GRID_LINE_ALPHA;
        context.strokeStyle = palette.gridLine;
        context.lineWidth = 1;
        context.beginPath();
        for (let column = 1; column < engine.columns; column++) {
            const x = layout.originX + column * layout.cellSize + 0.5;
            context.moveTo(x, layout.originY);
            context.lineTo(x, layout.originY + gridHeight);
        }
        for (let row = 1; row < engine.rows; row++) {
            const y = layout.originY + row * layout.cellSize + 0.5;
            context.moveTo(layout.originX, y);
            context.lineTo(layout.originX + gridWidth, y);
        }
        context.stroke();
        context.globalAlpha = 1;
    }

    private fillBoardTint(context: CanvasRenderingContext2D, palette: GamePalette, alpha: number): void {
        if (alpha <= 0) return;
        context.globalAlpha = alpha;
        context.fillStyle = palette.boardTint;
        context.fillRect(0, 0, this.boardWidth, this.boardHeight);
        context.globalAlpha = 1;
    }

    /** The board area below the HUD that the grid must fit in. */
    private gridArea(): GridArea {
        return {
            left: BOARD_PADDING_PX,
            top: HUD_RESERVED_HEIGHT_PX,
            width: Math.max(0, this.boardWidth - BOARD_PADDING_PX * 2),
            height: Math.max(0, this.boardHeight - HUD_RESERVED_HEIGHT_PX - BOARD_PADDING_PX),
        };
    }

    /** Exposes the rendered cell size to the stylesheet so the HUD and card scale with the grid. */
    private applyCellSizeVariable(cellSize: number): void {
        if (cellSize === this.appliedCellSize) return;
        this.appliedCellSize = cellSize;
        this.renderer.setStyle(
            this.hostRef.nativeElement,
            '--snake-cell-size',
            `${cellSize}px`,
            RendererStyleFlags2.DashCase
        );
    }

    private moveFocusToOverlay(): void {
        const activeElement = this.document.activeElement;
        if (activeElement instanceof HTMLElement) activeElement.blur();
        this.hostRef.nativeElement.focus({ preventScroll: true });
    }

    /** Resolves design tokens to concrete colours because canvas cannot read CSS variables. */
    private resolvePalette(): GamePalette {
        const style = getComputedStyle(this.hostRef.nativeElement);
        const token = (name: string): string => style.getPropertyValue(name).trim() || 'gray';
        return {
            boardTint: token('--color-background-body'),
            gridLine: token('--color-divider-subtle'),
            boardFrame: token('--accent-color'),
            snakeBody: token('--accent-color'),
            snakeHead: token('--color-ks-status-blue'),
            deathFlash: token('--color-ks-status-failed'),
            nodeFallbackColor: token('--accent-color'),
        };
    }
}

function swallowKeyEvent(event: KeyboardEvent): void {
    event.stopPropagation();
    event.stopImmediatePropagation();
}

/** Buttons activate on Space keyup, so keyup is cancelled for activation keys as well. */
function handleKeyUp(event: KeyboardEvent): void {
    swallowKeyEvent(event);
    if (isActivationKey(event)) event.preventDefault();
}

function isActivationKey(event: KeyboardEvent): boolean {
    return event.key === 'Enter' || event.key === ' ' || event.code === 'Space' || event.code === 'NumpadEnter';
}

function isFunctionKey(event: KeyboardEvent): boolean {
    return /^F\d{1,2}$/.test(event.key);
}

function isEditableTarget(target: EventTarget | null): boolean {
    return (
        target instanceof HTMLElement &&
        (target.isContentEditable || target.matches('input, textarea, select') || !!target.closest('.monaco-editor'))
    );
}

function formatClock(totalSeconds: number): string {
    const minutes = Math.floor(totalSeconds / 60);
    const seconds = totalSeconds % 60;
    return `${String(minutes).padStart(2, '0')}:${String(seconds).padStart(2, '0')}`;
}
