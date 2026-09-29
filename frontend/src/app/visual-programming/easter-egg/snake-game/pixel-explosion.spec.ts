import {
    BoardNodeSnapshot,
    buildExplosionParticles,
    choosePixelSize,
    DEFAULT_EXPLOSION_BUILD_OPTIONS,
    DEFAULT_EXPLOSION_STEP_OPTIONS,
    ExplosionBuildOptions,
    explosionDurationMs,
    ExplosionStepOptions,
    hasExplosionStarted,
    isExplosionFinished,
    stepExplosionParticles,
} from './pixel-explosion';

const AGENT_COLOR = '#685fff';
const PYTHON_COLOR = '#ffcf3f';

function createNode(overrides: Partial<BoardNodeSnapshot> = {}): BoardNodeSnapshot {
    return {
        rect: { left: 100, top: 100, width: 40, height: 20 },
        cornerRadius: 0,
        color: AGENT_COLOR,
        ...overrides,
    };
}

const BUILD_OPTIONS: ExplosionBuildOptions = {
    ...DEFAULT_EXPLOSION_BUILD_OPTIONS,
    angleSpreadRadians: 0,
    random: () => 0.5,
};

const STEP_OPTIONS: ExplosionStepOptions = {
    ...DEFAULT_EXPLOSION_STEP_OPTIONS,
    gravityPxPerMs2: 0,
    boardWidth: 10_000,
    boardHeight: 10_000,
};

describe('buildExplosionParticles', () => {
    it('fills the whole node with particles of its single colour', () => {
        const particles = buildExplosionParticles([createNode()], BUILD_OPTIONS);

        expect(particles.every((particle) => particle.size === 5)).toBe(true);
        expect(particles).toHaveLength(8 * 4);
        expect(new Set(particles.map((particle) => particle.color))).toEqual(new Set([AGENT_COLOR]));
    });

    it('keeps each node in its own colour', () => {
        const nodes = [
            createNode(),
            createNode({ rect: { left: 300, top: 100, width: 40, height: 20 }, color: PYTHON_COLOR }),
        ];

        const particles = buildExplosionParticles(nodes, BUILD_OPTIONS);

        expect(
            particles.filter((particle) => particle.x >= 300).every((particle) => particle.color === PYTHON_COLOR)
        ).toBe(true);
        expect(
            particles.filter((particle) => particle.x < 300).every((particle) => particle.color === AGENT_COLOR)
        ).toBe(true);
    });

    it('aims every particle radially away from its node centre', () => {
        const node = createNode();
        const centerX = node.rect.left + node.rect.width / 2;
        const centerY = node.rect.top + node.rect.height / 2;

        const particles = buildExplosionParticles([node], BUILD_OPTIONS);

        for (const particle of particles) {
            const offsetX = particle.x + particle.size / 2 - centerX;
            const offsetY = particle.y + particle.size / 2 - centerY;
            // Positive dot product: the velocity points away from the centre.
            expect(offsetX * particle.velocityX + offsetY * particle.velocityY).toBeGreaterThan(0);
        }
    });

    it('drops pixels outside rounded corners', () => {
        const square = createNode({ rect: { left: 0, top: 0, width: 50, height: 50 } });
        const rounded = { ...square, cornerRadius: 20 };

        expect(buildExplosionParticles([rounded], BUILD_OPTIONS).length).toBeLessThan(
            buildExplosionParticles([square], BUILD_OPTIONS).length
        );
    });

    it('coarsens the pixel size so the particle count stays within the cap', () => {
        const hugeNodes = Array.from({ length: 20 }, (_, index) =>
            createNode({ rect: { left: index * 500, top: 0, width: 480, height: 300 } })
        );

        const particles = buildExplosionParticles(hugeNodes, { ...BUILD_OPTIONS, maxParticles: 3000 });
        const pixelSize = choosePixelSize(hugeNodes, 3000, BUILD_OPTIONS.minimumPixelSize);

        expect(pixelSize).toBeGreaterThan(BUILD_OPTIONS.minimumPixelSize);
        expect(particles.length).toBeLessThanOrEqual(3000);
        expect(particles.every((particle) => particle.size === pixelSize)).toBe(true);
    });

    it('terminates and respects the cap when there are more nodes than allowed particles', () => {
        const manyNodes = Array.from({ length: 10 }, (_, index) =>
            createNode({ rect: { left: index * 50, top: 0, width: 40, height: 20 } })
        );

        const particles = buildExplosionParticles(manyNodes, { ...BUILD_OPTIONS, maxParticles: 5 });

        expect(particles.length).toBeLessThanOrEqual(5);
        expect(particles.length).toBeGreaterThan(0);
        expect(particles.every((particle) => particle.size === 40)).toBe(true);
    });

    it('returns no particles for an empty board', () => {
        expect(buildExplosionParticles([], BUILD_OPTIONS)).toEqual([]);
    });
});

describe('stepExplosionParticles', () => {
    it('holds every particle in place until the hold ends', () => {
        const particles = buildExplosionParticles([createNode()], BUILD_OPTIONS);
        const before = particles.map((particle) => ({ x: particle.x, y: particle.y }));

        stepExplosionParticles(particles, STEP_OPTIONS.holdDurationMs - 1, 16, STEP_OPTIONS);

        expect(hasExplosionStarted(STEP_OPTIONS.holdDurationMs - 1, STEP_OPTIONS)).toBe(false);
        expect(particles.map((particle) => ({ x: particle.x, y: particle.y }))).toEqual(before);
        expect(particles.every((particle) => particle.alpha === 1)).toBe(true);
    });

    it('starts every node at the same moment', () => {
        const nodes = [createNode(), createNode({ rect: { left: 2000, top: 100, width: 40, height: 20 } })];
        const particles = buildExplosionParticles(nodes, BUILD_OPTIONS);
        const before = particles.map((particle) => ({ x: particle.x, y: particle.y }));

        stepExplosionParticles(particles, STEP_OPTIONS.holdDurationMs + 16, 16, STEP_OPTIONS);

        particles.forEach((particle, index) => {
            expect({ x: particle.x, y: particle.y }).not.toEqual(before[index]);
            expect(particle.alpha).toBeLessThan(1);
        });
    });

    it('applies gravity to the vertical velocity', () => {
        const particles = buildExplosionParticles([createNode()], BUILD_OPTIONS);
        const velocityBefore = particles[0].velocityY;

        stepExplosionParticles(particles, STEP_OPTIONS.holdDurationMs + 100, 100, {
            ...STEP_OPTIONS,
            gravityPxPerMs2: 0.001,
        });

        expect(particles[0].velocityY).toBeCloseTo(velocityBefore + 0.1);
    });

    it('finishes within the configured duration', () => {
        const particles = buildExplosionParticles([createNode()], { ...BUILD_OPTIONS, random: Math.random });
        const durationMs = explosionDurationMs(BUILD_OPTIONS, STEP_OPTIONS);

        let elapsedMs = 0;
        while (elapsedMs < durationMs) {
            elapsedMs = Math.min(durationMs, elapsedMs + 16);
            stepExplosionParticles(particles, elapsedMs, 16, STEP_OPTIONS);
        }

        expect(durationMs).toBeLessThanOrEqual(2000);
        expect(isExplosionFinished(particles)).toBe(true);
    });

    it('drops particles that leave the board', () => {
        const particles = buildExplosionParticles([createNode()], BUILD_OPTIONS);

        stepExplosionParticles(particles, STEP_OPTIONS.holdDurationMs + 100, 100, {
            ...STEP_OPTIONS,
            boardWidth: 1,
            boardHeight: 1,
        });

        expect(isExplosionFinished(particles)).toBe(true);
    });
});
