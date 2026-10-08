import { HttpErrorResponse } from '@angular/common/http';
import { TestBed } from '@angular/core/testing';
import { Subject } from 'rxjs';

import {
    PollEvent,
    PythonCodeResult,
    PythonCodeRunService,
    RunPythonCodeRequest,
} from '../../../../services/python-code-run.service';
import { parseTestInputValues, PythonCodeTestRun } from './python-code-test-run';

const REQUEST: RunPythonCodeRequest = {
    python_code_id: 5,
    code: 'def main(trigger_payload): pass',
    entrypoint: 'main',
    libraries: [],
    variables: { trigger_payload: { order: 1 } },
};

function result(overrides: Partial<PythonCodeResult>): PythonCodeResult {
    return {
        execution_id: 'exec-1',
        status: 'completed',
        result_data: '{"ok": true}',
        returncode: 0,
        stderr: '',
        stdout: '',
        ...overrides,
    };
}

describe('PythonCodeTestRun', () => {
    let start$: Subject<{ execution_id: string }>;
    let poll$: Subject<PollEvent>;
    let service: { runPythonCode: ReturnType<typeof vi.fn>; pollResultWithEvents: ReturnType<typeof vi.fn> };
    let codeRun: PythonCodeTestRun;

    beforeEach(() => {
        start$ = new Subject();
        poll$ = new Subject();
        service = {
            runPythonCode: vi.fn(() => start$),
            pollResultWithEvents: vi.fn(() => poll$),
        };
        TestBed.configureTestingModule({ providers: [{ provide: PythonCodeRunService, useValue: service }] });
        codeRun = TestBed.runInInjectionContext(() => new PythonCodeTestRun());
    });

    function messages(): string[] {
        return codeRun.logs().map((entry) => `${entry.type}: ${entry.message}`);
    }

    function startAndPoll(): void {
        codeRun.run(REQUEST);
        start$.next({ execution_id: 'exec-1' });
    }

    it('is idle with an empty terminal before a run', () => {
        expect(codeRun.status()).toBe('idle');
        expect(codeRun.isRunning()).toBe(false);
        expect(codeRun.logs()).toEqual([]);
        expect(codeRun.terminalHeight()).toBe(150);
    });

    it('sends the request as is and logs its parameters', () => {
        codeRun.run(REQUEST);

        expect(service.runPythonCode).toHaveBeenCalledWith(REQUEST);
        expect(codeRun.status()).toBe('processing');
        expect(messages()).toEqual([
            'info: Starting function main()...',
            'info: Parameters: {"trigger_payload":{"order":1}}',
        ]);
    });

    it('polls the execution, logging the first polling attempt once', () => {
        startAndPoll();
        poll$.next({ type: 'polling', attempt: 1 });
        poll$.next({ type: 'polling', attempt: 2 });

        expect(service.pollResultWithEvents).toHaveBeenCalledWith('exec-1');
        expect(messages().slice(2)).toEqual(['polling: Processing...']);
        expect(codeRun.isRunning()).toBe(true);
    });

    it('logs the output and result of a completed run', () => {
        startAndPoll();
        poll$.next({ type: 'result', data: result({ stdout: 'printed', stderr: 'warned' }) });

        expect(messages().slice(2)).toEqual(['stdout: printed', 'stderr: warned', 'result: {"ok": true}']);
        expect(codeRun.status()).toBe('done');
        expect(codeRun.isRunning()).toBe(false);
    });

    it('logs an empty result as such', () => {
        startAndPoll();
        poll$.next({ type: 'result', data: result({ result_data: null }) });

        expect(messages().at(-1)).toBe('result: (empty result)');
    });

    it('logs a failed run with its return code', () => {
        startAndPoll();
        poll$.next({ type: 'result', data: result({ status: 'error', returncode: 1, stderr: 'Traceback' }) });

        expect(messages().slice(2)).toEqual(['stderr: Traceback', 'error: Execution failed (return code: 1)']);
        expect(codeRun.status()).toBe('error');
    });

    it('logs an HTTP error of the run request', () => {
        codeRun.run(REQUEST);
        const httpError = new HttpErrorResponse({ status: 400, url: '/run-python-code/' });
        start$.error(httpError);

        expect(messages().at(-1)).toBe(`error: Error: ${httpError.message}`);
        expect(codeRun.error()).toBe(httpError.message);
        expect(codeRun.status()).toBe('error');
        expect(codeRun.isRunning()).toBe(false);
    });

    it('ignores a run while one is in flight', () => {
        codeRun.run(REQUEST);
        codeRun.run({ ...REQUEST, python_code_id: 6 });

        expect(service.runPythonCode).toHaveBeenCalledTimes(1);
    });

    it('starts each run with a clean terminal and state', () => {
        startAndPoll();
        poll$.next({ type: 'result', data: result({ status: 'error', returncode: 1 }) });
        poll$ = new Subject();
        start$ = new Subject();

        startAndPoll();

        expect(messages()).toHaveLength(2);
        expect(codeRun.result()).toBeNull();
        expect(codeRun.status()).toBe('processing');
    });

    it('reset stops a run in flight and returns to idle with an empty terminal', () => {
        codeRun.run(REQUEST);

        codeRun.reset();
        start$.next({ execution_id: 'exec-1' });

        expect(service.pollResultWithEvents).not.toHaveBeenCalled();
        expect(codeRun.isRunning()).toBe(false);
        expect(codeRun.logs()).toEqual([]);
        expect(codeRun.status()).toBe('idle');

        codeRun.run(REQUEST);
        expect(service.runPythonCode).toHaveBeenCalledTimes(2);
    });

    it('reset clears the result and error of a finished run', () => {
        codeRun.run(REQUEST);
        start$.error(new Error('boom'));
        expect(codeRun.status()).toBe('error');

        codeRun.reset();

        expect(codeRun.error()).toBeNull();
        expect(codeRun.result()).toBeNull();
        expect(codeRun.status()).toBe('idle');
    });

    it('clears the logs and keeps a resized terminal height', () => {
        codeRun.run(REQUEST);
        codeRun.clearLogs();
        codeRun.setTerminalHeight(320);

        expect(codeRun.logs()).toEqual([]);
        expect(codeRun.terminalHeight()).toBe(320);
    });
});

describe('parseTestInputValues', () => {
    it('parses JSON values and keeps any other text as a string', () => {
        expect(parseTestInputValues({ count: '3', flags: '[true]', name: 'Ada', quoted: '"x"' })).toEqual({
            count: 3,
            flags: [true],
            name: 'Ada',
            quoted: 'x',
        });
    });
});
