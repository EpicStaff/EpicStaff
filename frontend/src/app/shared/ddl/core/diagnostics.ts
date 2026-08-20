/** A position in the source, 1-based line and column. */
export interface Position {
    line: number;
    col: number;
}

export interface Span {
    start: Position;
    end: Position;
}

export type Severity = 'error' | 'warning';

export interface Diagnostic {
    severity: Severity;
    /** Stable machine code, e.g. "unknown-type". */
    code: string;
    message: string;
    span?: Span;
}

export function error(code: string, message: string, span?: Span): Diagnostic {
    return { severity: 'error', code, message, span };
}

export function warning(code: string, message: string, span?: Span): Diagnostic {
    return { severity: 'warning', code, message, span };
}

/** Render a diagnostic as a single human-readable line. */
export function formatDiagnostic(d: Diagnostic): string {
    const loc = d.span ? `${d.span.start.line}:${d.span.start.col} ` : '';
    return `${loc}${d.severity} [${d.code}]: ${d.message}`;
}
