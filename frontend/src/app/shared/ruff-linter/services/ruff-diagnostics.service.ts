import { Injectable } from '@angular/core';

import type { RuffDiagnostic } from '../models/ruff-result.model';

const RUFF_OWNER = 'ruff-linter';

/** Monaco instance from ngx-monaco-editor-v2 (loaded via AMD to window.monaco). */
function getMonaco(): typeof import('monaco-editor') {
    const monaco = (window as unknown as { monaco?: typeof import('monaco-editor') }).monaco;
    if (!monaco) {
        throw new Error('[RuffDiagnostics] window.monaco not found - Monaco may not be loaded yet');
    }
    return monaco;
}

/** Detects "Expected X, found Y" style syntax error for unclosed parentheses. */
const UNCLOSED_PAREN_PATTERN = /Expected [`'"]?[,\)][`'"]?,?\s*found\s+/i;

@Injectable({
    providedIn: 'root',
})
export class RuffDiagnosticsService {
    toMonacoMarkers(diagnostics: RuffDiagnostic[], code?: string) {
        const monaco = getMonaco();
        const markers = diagnostics.map((d) => this.toMonacoMarker(d, monaco, code));
        return this.deduplicateMarkers(markers);
    }

    /** Removes duplicate markers that have the same range and message */
    private deduplicateMarkers(
        markers: Array<{
            startLineNumber: number;
            startColumn: number;
            endLineNumber: number;
            endColumn: number;
            severity: number;
            message: string;
        }>
    ): typeof markers {
        const seen = new Set<string>();
        return markers.filter((m) => {
            const key = `${m.startLineNumber}:${m.startColumn}-${m.endLineNumber}:${m.endColumn}|${m.message}`;
            if (seen.has(key)) return false;
            seen.add(key);
            return true;
        });
    }

    private toMonacoMarker(diagnostic: RuffDiagnostic, monaco: typeof import('monaco-editor'), code?: string) {
        const severity = this.ruffCodeToMonacoSeverity(diagnostic.code, monaco);

        let startLine = diagnostic.start_location.row;
        let startCol = diagnostic.start_location.column;
        let endLine = diagnostic.end_location.row;
        let endCol = diagnostic.end_location.column;
        let message = diagnostic.code ? `[${diagnostic.code}] ${diagnostic.message}` : diagnostic.message;

        // For invalid-syntax "Expected `,`/`)`, found ..." → underline unclosed parenthesis
        if (code && diagnostic.code === 'invalid-syntax' && UNCLOSED_PAREN_PATTERN.test(diagnostic.message)) {
            const adjusted = this.findUnclosedParenthesisRange(code, startLine, startCol);
            if (adjusted) {
                startLine = adjusted.startLine;
                startCol = adjusted.startCol;
                endLine = adjusted.endLine;
                endCol = adjusted.endCol;
                message = '[invalid-syntax] Missing closing parenthesis `)`';
            }
        }
        // Monaco needs endColumn > startColumn for visible underlines
        const marker = {
            startLineNumber: startLine,
            startColumn: startCol,
            endLineNumber: endLine,
            endColumn: startLine === endLine && startCol === endCol ? startCol + 1 : endCol,
            severity,
            message,
        };
        return marker;
    }

    /**
     * Finds the range of an unclosed parenthesis by scanning backward from the error position.
     * Returns Monaco 1-based { startLine, startCol, endLine, endCol } or null if not found.
     */
    private findUnclosedParenthesisRange(
        code: string,
        errorRow: number,
        errorCol: number
    ): { startLine: number; startCol: number; endLine: number; endCol: number } | null {
        const lines = code.split(/\r?\n/);
        if (errorRow < 1 || errorRow > lines.length) return null;
        const errorLine = lines[errorRow - 1];
        const errorIdx = Math.min(errorCol - 1, errorLine.length);
        const beforeError = errorLine.slice(0, errorIdx);

        let parenDepth = 0;
        for (let i = beforeError.length - 1; i >= 0; i--) {
            const ch = beforeError[i];
            if (ch === ')') parenDepth++;
            else if (ch === '(') {
                if (parenDepth === 0) {
                    return {
                        startLine: errorRow,
                        startCol: i + 1,
                        endLine: errorRow,
                        endCol: beforeError.length + 1,
                    };
                }
                parenDepth--;
            }
        }

        // No ( on same line; search previous lines for unclosed (
        for (let row = errorRow - 2; row >= 0; row--) {
            const line = lines[row];
            parenDepth = 0;
            for (let i = line.length - 1; i >= 0; i--) {
                const ch = line[i];
                if (ch === ')') parenDepth++;
                else if (ch === '(') {
                    if (parenDepth === 0) {
                        return {
                            startLine: row + 1,
                            startCol: i + 1,
                            endLine: row + 1,
                            endCol: line.length + 1,
                        };
                    }
                    parenDepth--;
                }
            }
        }
        return null;
    }

    private ruffCodeToMonacoSeverity(code: string | null, monaco: typeof import('monaco-editor')) {
        if (!code) {
            return monaco.MarkerSeverity.Warning;
        }
        const first = code.charAt(0).toUpperCase();
        switch (first) {
            case 'E':
            case 'F':
                return monaco.MarkerSeverity.Error;
            case 'W':
                return monaco.MarkerSeverity.Warning;
            default:
                return monaco.MarkerSeverity.Hint;
        }
    }

    setMarkers(editor: import('monaco-editor').editor.IStandaloneCodeEditor, diagnostics: RuffDiagnostic[]): void {
        const monaco = getMonaco();
        const model = editor.getModel();
        if (!model) {
            console.warn('[RuffDiagnostics] setMarkers() - editor has no model!');
            return;
        }
        const code = model.getValue();
        const markers = this.toMonacoMarkers(diagnostics, code);
        monaco.editor.setModelMarkers(model, RUFF_OWNER, markers);
    }

    clearMarkers(editor: import('monaco-editor').editor.IStandaloneCodeEditor): void {
        const monaco = getMonaco();
        const model = editor.getModel();
        if (!model) {
            return;
        }
        monaco.editor.setModelMarkers(model, RUFF_OWNER, []);
    }
}
