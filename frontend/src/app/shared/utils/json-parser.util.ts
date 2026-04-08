export function safeJsonParse(jsonString: string): unknown {
    if (!jsonString || typeof jsonString !== 'string') {
        return jsonString;
    }

    try {
        return JSON.parse(jsonString);
    } catch {
        try {
            const parsed = JSON.parse(jsonString);
            if (typeof parsed === 'string') {
                return safeJsonParse(parsed);
            }
            return parsed;
        } catch {
            return jsonString;
        }
    }
}

export function parseNestedJson(obj: unknown, maxDepth = 3, currentDepth = 0): unknown {
    if (currentDepth >= maxDepth) {
        return obj;
    }

    if (typeof obj === 'string') {
        return safeJsonParse(obj);
    }

    if (Array.isArray(obj)) {
        return obj.map((item: unknown) => parseNestedJson(item, maxDepth, currentDepth + 1));
    }

    if (obj && typeof obj === 'object') {
        const parsed: Record<string, unknown> = {};
        for (const [key, value] of Object.entries(obj as Record<string, unknown>)) {
            parsed[key] = parseNestedJson(value, maxDepth, currentDepth + 1);
        }
        return parsed;
    }

    return obj;
}

export function formatExecutionDataForDisplay(executionData: Record<string, unknown>): Record<string, unknown> {
    if (!executionData || typeof executionData !== 'object') {
        return executionData;
    }

    const dataCopy: Record<string, unknown> = JSON.parse(JSON.stringify(executionData)) as Record<string, unknown>;

    Object.keys(dataCopy).forEach((field) => {
        const value = dataCopy[field];

        if (value && typeof value === 'string') {
            const trimmedValue = value.trim();

            if (
                (trimmedValue.startsWith('{') && trimmedValue.endsWith('}')) ||
                (trimmedValue.startsWith('"') && trimmedValue.endsWith('"')) ||
                (trimmedValue.startsWith('[') && trimmedValue.endsWith(']')) ||
                (trimmedValue.startsWith('""') && trimmedValue.endsWith('""'))
            ) {
                dataCopy[field] = safeJsonParse(trimmedValue);
            }
        } else if (value && typeof value === 'object') {
            dataCopy[field] = parseNestedJson(value);
        }
    });

    return dataCopy;
}
