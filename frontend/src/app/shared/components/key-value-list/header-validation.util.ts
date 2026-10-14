const HEADER_NAME_PATTERN = /^[!#$%&'*+\-.^_`|~0-9A-Za-z]+$/;
const LINE_BREAK_PATTERN = /[\r\n]/;

export const HEADER_NAME_REQUIRED_ERROR = 'Header name is required';
export const HEADER_NAME_FORMAT_ERROR = "Header names can't contain spaces or special characters";
export const HEADER_NAME_DUPLICATE_ERROR = 'Duplicate header name';
export const HEADER_VALUE_LINE_BREAK_ERROR = "Header values can't contain line breaks";

/** Returns the first problem with a header row, or null. A row with no name and no value is ignored. */
export function getHeaderRowError(name: string, value: string, otherNames: readonly string[]): string | null {
    const trimmedName = name.trim();
    if (!trimmedName) return value.trim() ? HEADER_NAME_REQUIRED_ERROR : null;
    if (!HEADER_NAME_PATTERN.test(trimmedName)) return HEADER_NAME_FORMAT_ERROR;
    const lowerName = trimmedName.toLowerCase();
    if (otherNames.some((other) => other.trim().toLowerCase() === lowerName)) return HEADER_NAME_DUPLICATE_ERROR;
    if (LINE_BREAK_PATTERN.test(value)) return HEADER_VALUE_LINE_BREAK_ERROR;
    return null;
}
