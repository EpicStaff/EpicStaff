import type * as monaco from 'monaco-editor';

import type { Diagnostic, Severity, Span } from '../core/diagnostics';

type MonacoRange = Pick<monaco.editor.IMarkerData, 'startLineNumber' | 'startColumn' | 'endLineNumber' | 'endColumn'>;

/**
 * Maps the DDL library's severities onto `monaco.MarkerSeverity` (Error = 8,
 * Warning = 4). `monaco-editor` is only imported as a type here (never as a
 * value — see the module doc in `register-ddl-language.ts`), so the numeric
 * values are inlined and cast rather than read off the real enum.
 */
const DDL_SEVERITY_TO_MONACO: Record<Severity, monaco.MarkerSeverity> = {
    error: 8 as monaco.MarkerSeverity,
    warning: 4 as monaco.MarkerSeverity,
};

/**
 * Converts DDL diagnostics into Monaco marker data for `model`.
 *
 * DDL spans are 1-based line/col with an *exclusive* end column, which is
 * exactly how Monaco ranges work too, so most spans map over unchanged.
 * Two edge cases need help:
 *  - no span at all → underline the whole of line 1.
 *  - a zero-width span on a single line (endCol <= startCol, e.g. the
 *    indentation diagnostics which point at column 1..1) → expand to the
 *    full line so the marker is actually visible.
 */
export function diagnosticsToMarkers(
    diagnostics: readonly Diagnostic[],
    model: monaco.editor.ITextModel
): monaco.editor.IMarkerData[] {
    return diagnostics.map((diagnostic) => toMarkerData(diagnostic, model));
}

function toMarkerData(diagnostic: Diagnostic, model: monaco.editor.ITextModel): monaco.editor.IMarkerData {
    const range = diagnostic.span ? spanToRange(diagnostic.span, model) : fullLineRange(1, model);
    return {
        severity: DDL_SEVERITY_TO_MONACO[diagnostic.severity],
        message: diagnostic.message,
        code: diagnostic.code,
        ...range,
    };
}

function spanToRange(span: Span, model: monaco.editor.ITextModel): MonacoRange {
    const { start, end } = span;
    if (start.line === end.line && end.col <= start.col) {
        return fullLineRange(start.line, model);
    }
    return {
        startLineNumber: start.line,
        startColumn: start.col,
        endLineNumber: end.line,
        endColumn: end.col,
    };
}

function fullLineRange(line: number, model: monaco.editor.ITextModel): MonacoRange {
    return {
        startLineNumber: line,
        startColumn: 1,
        endLineNumber: line,
        endColumn: model.getLineMaxColumn(line),
    };
}
