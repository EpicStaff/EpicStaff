export const MAX_POSITION_MAGNITUDE = 1_000_000;

export function isFiniteNumber(value: unknown): value is number {
    return typeof value === 'number' && Number.isFinite(value);
}

export function clamp(value: number, min: number, max: number): number {
    return Math.min(Math.max(value, min), max);
}

export function clampPosition(value: number): number {
    return clamp(value, -MAX_POSITION_MAGNITUDE, MAX_POSITION_MAGNITUDE);
}
