/** An axis-aligned rectangle in overlay-local CSS pixels. */
export interface PixelRect {
    left: number;
    top: number;
    width: number;
    height: number;
}

/** Visual snapshot of one canvas node: where it sits, its corner radius and its node-type colour. */
export interface BoardNodeSnapshot {
    rect: PixelRect;
    cornerRadius: number;
    color: string;
}

/** One square of the explosion; mutated in place by `stepExplosionParticles`. */
export interface ExplosionParticle {
    x: number;
    y: number;
    size: number;
    color: string;
    velocityX: number;
    velocityY: number;
    fadeDurationMs: number;
    alpha: number;
}

export interface ExplosionBuildOptions {
    maxParticles: number;
    minimumPixelSize: number;
    minimumSpeedPxPerMs: number;
    maximumSpeedPxPerMs: number;
    /** Maximum random deviation (radians) from the straight-out direction. */
    angleSpreadRadians: number;
    minimumFadeDurationMs: number;
    maximumFadeDurationMs: number;
    random: () => number;
}

export interface ExplosionStepOptions {
    /** Time the solid blocks are held before every node explodes at once. */
    holdDurationMs: number;
    gravityPxPerMs2: number;
    boardWidth: number;
    boardHeight: number;
}

export const DEFAULT_EXPLOSION_BUILD_OPTIONS: Omit<ExplosionBuildOptions, 'random'> = {
    maxParticles: 6000,
    minimumPixelSize: 5,
    minimumSpeedPxPerMs: 0.12,
    maximumSpeedPxPerMs: 0.6,
    angleSpreadRadians: 0.6,
    minimumFadeDurationMs: 900,
    maximumFadeDurationMs: 1200,
};

export const DEFAULT_EXPLOSION_STEP_OPTIONS: Omit<ExplosionStepOptions, 'boardWidth' | 'boardHeight'> = {
    holdDurationMs: 400,
    gravityPxPerMs2: 0.0004,
};

/** Upper bound of the whole intro: the hold plus the slowest possible fade. */
export function explosionDurationMs(
    buildOptions: Pick<ExplosionBuildOptions, 'maximumFadeDurationMs'>,
    stepOptions: Pick<ExplosionStepOptions, 'holdDurationMs'>
): number {
    return stepOptions.holdDurationMs + buildOptions.maximumFadeDurationMs;
}

/** Returns the smallest pixel size (at least `minimumPixelSize`) whose particle count stays within `maxParticles`. */
export function choosePixelSize(
    nodes: readonly BoardNodeSnapshot[],
    maxParticles: number,
    minimumPixelSize: number
): number {
    // At the largest node dimension every node is a single cell, so the search always terminates there.
    const largestDimension = Math.max(
        1,
        ...nodes.map((node) => Math.ceil(Math.max(node.rect.width, node.rect.height)))
    );
    let pixelSize = Math.max(1, minimumPixelSize);
    while (pixelSize < largestDimension && countCells(nodes, pixelSize) > maxParticles) {
        pixelSize += 1;
    }
    return pixelSize;
}

/** Splits every node into solid squares of its colour, each aimed radially away from its node's centre. */
export function buildExplosionParticles(
    allNodes: readonly BoardNodeSnapshot[],
    options: ExplosionBuildOptions
): ExplosionParticle[] {
    // Each node yields at least one particle, so only the first `maxParticles` nodes can fit under the cap.
    const nodes = allNodes.slice(0, Math.max(0, options.maxParticles));
    const pixelSize = choosePixelSize(nodes, options.maxParticles, options.minimumPixelSize);
    const particles: ExplosionParticle[] = [];

    for (const node of nodes) {
        const columns = Math.ceil(node.rect.width / pixelSize);
        const rows = Math.ceil(node.rect.height / pixelSize);
        const centerX = node.rect.left + node.rect.width / 2;
        const centerY = node.rect.top + node.rect.height / 2;

        for (let row = 0; row < rows; row++) {
            for (let column = 0; column < columns; column++) {
                if (!isCellInsideShape(node, pixelSize, column, row)) continue;
                const x = node.rect.left + column * pixelSize;
                const y = node.rect.top + row * pixelSize;
                const offsetX = x + pixelSize / 2 - centerX;
                const offsetY = y + pixelSize / 2 - centerY;
                const outwardAngle =
                    offsetX === 0 && offsetY === 0 ? options.random() * Math.PI * 2 : Math.atan2(offsetY, offsetX);
                const angle = outwardAngle + (options.random() - 0.5) * 2 * options.angleSpreadRadians;
                const speed = lerp(options.minimumSpeedPxPerMs, options.maximumSpeedPxPerMs, options.random());
                particles.push({
                    x,
                    y,
                    size: pixelSize,
                    color: node.color,
                    velocityX: Math.cos(angle) * speed,
                    velocityY: Math.sin(angle) * speed,
                    fadeDurationMs: lerp(
                        options.minimumFadeDurationMs,
                        options.maximumFadeDurationMs,
                        options.random()
                    ),
                    alpha: 1,
                });
            }
        }
    }

    particles.sort((first, second) => (first.color < second.color ? -1 : first.color > second.color ? 1 : 0));
    return particles;
}

/** True once the hold is over, i.e. every node has exploded. */
export function hasExplosionStarted(elapsedMs: number, options: Pick<ExplosionStepOptions, 'holdDurationMs'>): boolean {
    return elapsedMs >= options.holdDurationMs;
}

/** Advances every particle by `deltaMs` (flight, gravity, fade) given the time since the intro began. */
export function stepExplosionParticles(
    particles: ExplosionParticle[],
    elapsedMs: number,
    deltaMs: number,
    options: ExplosionStepOptions
): void {
    if (!hasExplosionStarted(elapsedMs, options)) return;
    const flightMs = elapsedMs - options.holdDurationMs;
    // The first frame after the hold only moves for the part of the frame that is past the hold.
    const movingMs = Math.min(deltaMs, flightMs);

    for (const particle of particles) {
        if (particle.alpha <= 0) continue;
        particle.velocityY += options.gravityPxPerMs2 * movingMs;
        particle.x += particle.velocityX * movingMs;
        particle.y += particle.velocityY * movingMs;
        particle.alpha = Math.max(0, 1 - flightMs / particle.fadeDurationMs);
        if (isOutsideBoard(particle, options)) particle.alpha = 0;
    }
}

/** True once every particle has fully faded or left the board. */
export function isExplosionFinished(particles: readonly ExplosionParticle[]): boolean {
    return particles.every((particle) => particle.alpha <= 0);
}

function isOutsideBoard(particle: ExplosionParticle, options: ExplosionStepOptions): boolean {
    return (
        particle.x + particle.size < 0 ||
        particle.y + particle.size < 0 ||
        particle.x > options.boardWidth ||
        particle.y > options.boardHeight
    );
}

function countCells(nodes: readonly BoardNodeSnapshot[], pixelSize: number): number {
    return nodes.reduce(
        (total, node) => total + Math.ceil(node.rect.width / pixelSize) * Math.ceil(node.rect.height / pixelSize),
        0
    );
}

function isCellInsideShape(node: BoardNodeSnapshot, pixelSize: number, column: number, row: number): boolean {
    const radius = Math.min(node.cornerRadius, node.rect.width / 2, node.rect.height / 2);
    if (radius <= 0) return true;
    const centerX = Math.min(column * pixelSize + pixelSize / 2, node.rect.width);
    const centerY = Math.min(row * pixelSize + pixelSize / 2, node.rect.height);
    const cornerX = clamp(centerX, radius, node.rect.width - radius);
    const cornerY = clamp(centerY, radius, node.rect.height - radius);
    const distanceX = centerX - cornerX;
    const distanceY = centerY - cornerY;
    return distanceX * distanceX + distanceY * distanceY <= radius * radius;
}

function clamp(value: number, minimum: number, maximum: number): number {
    return Math.min(maximum, Math.max(minimum, value));
}

function lerp(start: number, end: number, progress: number): number {
    return start + (end - start) * progress;
}
