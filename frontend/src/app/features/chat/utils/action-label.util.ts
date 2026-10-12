/** A readable label for an action object: its label, text or title, else its compact JSON. Always plain text. */
export function actionLabel(action: unknown): string {
    if (action && typeof action === 'object') {
        const record = action as Record<string, unknown>;
        const label = record['label'] ?? record['text'] ?? record['title'];
        if (typeof label === 'string') return label;
    }
    return JSON.stringify(action);
}
