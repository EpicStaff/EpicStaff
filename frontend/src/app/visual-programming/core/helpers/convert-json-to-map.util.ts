/**
 * Interface representing a position point
 */
export interface Position {
    x: number;
    y: number;
}

/**
 * Type for a map of element IDs to their relative positions
 */
export type PositionsMap = Map<string, Position>;

/**
 * Converts a JSON object to a Map for positions data.
 * This is useful when working with serialized data that might come from a database or JSON.
 *
 * @param jsonPositions The positions data that might be a Map or a plain object from JSON
 * @returns A proper Map of position data
 */
export function convertJsonToMap(jsonPositions: unknown): PositionsMap {
    // If it's already a Map, return it
    if (jsonPositions instanceof Map) {
        return jsonPositions;
    }

    // Otherwise, convert from plain object to Map
    const positionsMap = new Map<string, Position>();

    // If it's a plain object (from JSON)
    if (jsonPositions && typeof jsonPositions === 'object') {
        Object.entries(jsonPositions).forEach(([key, value]) => {
            // Ensure value is an object with x and y properties
            const position = value as Position;
            if (position && typeof position === 'object' && 'x' in position && 'y' in position) {
                positionsMap.set(key, { x: position.x, y: position.y });
            }
        });
    }

    return positionsMap;
}

/**
 * Converts a positions Map to a plain object for storage in databases or JSON serialization
 *
 * @param positionsMap The Map of positions to convert to a plain object
 * @returns A plain object representation of the positions map
 */
export function convertMapToJson(positionsMap: PositionsMap): Record<string, Position> {
    const result: Record<string, Position> = {};

    positionsMap.forEach((position, key) => {
        result[key] = { x: position.x, y: position.y };
    });

    return result;
}
