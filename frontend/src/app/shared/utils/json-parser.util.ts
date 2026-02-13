export function safeJsonParse(jsonString: string): any {
    if (!jsonString || typeof jsonString !== 'string') {
        return jsonString;
    }

    try {       
        return JSON.parse(jsonString);
    } catch (e) {       
        try {           
            const parsed = JSON.parse(jsonString);
            if (typeof parsed === 'string') {             
                return safeJsonParse(parsed);
            }
            return parsed;
        } catch (e2) {           
            return jsonString;
        }
    }
}

export function parseNestedJson(obj: any, maxDepth = 3, currentDepth = 0): any {
    if (currentDepth >= maxDepth) {
        return obj;
    }

    if (typeof obj === 'string') {
        return safeJsonParse(obj);
    }

    if (Array.isArray(obj)) {
        return obj.map((item) =>
            parseNestedJson(item, maxDepth, currentDepth + 1),
        );
    }

    if (obj && typeof obj === 'object') {
        const parsed: any = {};
        for (const [key, value] of Object.entries(obj)) {
            parsed[key] = parseNestedJson(value, maxDepth, currentDepth + 1);
        }
        return parsed;
    }

    return obj;
}

export function formatExecutionDataForDisplay(
    executionData: Record<string, any>,
): Record<string, any> {
    if (!executionData || typeof executionData !== 'object') {
        return executionData;
    }

    const dataCopy = JSON.parse(JSON.stringify(executionData));
   
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
        }
                
        else if (value && typeof value === 'object') {
            dataCopy[field] = parseNestedJson(value);
        }
    });

    return dataCopy;
}
