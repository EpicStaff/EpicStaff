import { computed, DestroyRef, inject, Signal, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { Subscription, switchMap } from 'rxjs';

import {
    PollEvent,
    PythonCodeResult,
    PythonCodeRunService,
    RunPythonCodeRequest,
} from '../../../../services/python-code-run.service';
import { TerminalStatus } from '../../python-node-panel/python-terminal/python-terminal.component';
import { TerminalLogEntry, TerminalLogType } from '../../python-node-panel/python-terminal/terminal-log.model';

const DEFAULT_TERMINAL_HEIGHT = 150;

/**
 * Test values typed as text (the Python node's test inputs): each one that parses as JSON becomes that
 * value, any other stays the string.
 */
export function parseTestInputValues(values: Record<string, string>): Record<string, unknown> {
    return Object.fromEntries(Object.entries(values).map(([key, value]) => [key, parseTestInputValue(value)]));
}

function parseTestInputValue(raw: string): unknown {
    try {
        return JSON.parse(raw);
    } catch {
        return raw;
    }
}

/**
 * A code-only run of a node's stored Python code (run-python-code, then polling for the result) and the
 * terminal that shows it (`app-python-terminal`). Create it in a field initializer: it injects
 * `PythonCodeRunService` and the panel's `DestroyRef`, which stops the polling when the panel goes away.
 */
export class PythonCodeTestRun {
    private readonly pythonCodeRunService = inject(PythonCodeRunService);
    private readonly destroyRef = inject(DestroyRef);
    private currentRun: Subscription | null = null;

    private readonly logsSignal = signal<TerminalLogEntry[]>([]);
    public readonly logs: Signal<TerminalLogEntry[]> = this.logsSignal.asReadonly();
    private readonly resultSignal = signal<PythonCodeResult | null>(null);
    public readonly result: Signal<PythonCodeResult | null> = this.resultSignal.asReadonly();
    private readonly errorSignal = signal<string | null>(null);
    public readonly error: Signal<string | null> = this.errorSignal.asReadonly();
    private readonly isRunningSignal = signal(false);
    public readonly isRunning: Signal<boolean> = this.isRunningSignal.asReadonly();
    private readonly terminalHeightSignal = signal(DEFAULT_TERMINAL_HEIGHT);
    public readonly terminalHeight: Signal<number> = this.terminalHeightSignal.asReadonly();

    public readonly status = computed<TerminalStatus>(() => {
        if (this.isRunning()) return 'processing';
        if (this.error()) return 'error';
        const result = this.result();
        if (result) return result.status === 'completed' ? 'done' : 'error';
        return 'idle';
    });

    /** Runs the stored code `request.python_code_id` with `request.variables` as its arguments; ignored while a run is in flight. */
    public run(request: RunPythonCodeRequest): void {
        if (this.isRunning()) return;
        this.isRunningSignal.set(true);
        this.resultSignal.set(null);
        this.errorSignal.set(null);
        this.logsSignal.set([]);

        this.addLog('info', 'Starting function main()...');
        this.addLog('info', `Parameters: ${JSON.stringify(request.variables)}`);

        this.currentRun = this.pythonCodeRunService
            .runPythonCode(request)
            .pipe(
                switchMap(({ execution_id }) => this.pythonCodeRunService.pollResultWithEvents(execution_id)),
                takeUntilDestroyed(this.destroyRef)
            )
            .subscribe({
                next: (event: PollEvent) => this.onPollEvent(event),
                error: (error: Error) => {
                    const message = error.message || 'Unknown error';
                    this.errorSignal.set(message);
                    this.isRunningSignal.set(false);
                    this.addLog('error', `Error: ${message}`);
                },
            });
    }

    /** Back to before any run, stopping a run in flight: e.g. when the panel shows another node. */
    public reset(): void {
        this.currentRun?.unsubscribe();
        this.currentRun = null;
        this.isRunningSignal.set(false);
        this.resultSignal.set(null);
        this.errorSignal.set(null);
        this.logsSignal.set([]);
    }

    public clearLogs(): void {
        this.logsSignal.set([]);
    }

    public setTerminalHeight(height: number): void {
        this.terminalHeightSignal.set(height);
    }

    private onPollEvent(event: PollEvent): void {
        if (event.type === 'polling') {
            if (event.attempt === 1) {
                this.addLog('polling', 'Processing...');
            }
            return;
        }
        const result = event.data;
        this.resultSignal.set(result);
        this.isRunningSignal.set(false);

        if (result.stdout) {
            this.addLog('stdout', result.stdout);
        }
        if (result.stderr) {
            this.addLog('stderr', result.stderr);
        }
        if (result.status === 'completed') {
            this.addLog('result', result.result_data || '(empty result)');
        } else {
            this.addLog('error', `Execution failed (return code: ${result.returncode})`);
        }
    }

    private addLog(type: TerminalLogType, message: string): void {
        this.logsSignal.update((logs) => [...logs, { timestamp: new Date(), type, message }]);
    }
}
