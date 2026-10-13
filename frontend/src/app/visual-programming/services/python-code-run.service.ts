import { HttpClient, HttpErrorResponse, HttpHeaders } from '@angular/common/http';
import { inject, Injectable } from '@angular/core';
import { merge, Observable, of, throwError, timer } from 'rxjs';
import { catchError, map, switchMap, takeWhile } from 'rxjs/operators';

import { ConfigService } from '../../services/config';

/** Poll cadence and limits for python-code-result. */
const POLL_INITIAL_DELAY_MS = 1000;
const POLL_INTERVAL_MS = 2000;
/**
 * How long past the node's execution timeout the panel keeps waiting for a result: the sandbox stops the code
 * at the timeout, but queueing, installing the libraries (not limited by the timeout) and publishing the
 * result come on top of it.
 */
const POLL_DEADLINE_GRACE_MS = 60_000;

const MAX_NOT_FOUND_RETRIES = 3;

/**
 * The kinds of node whose stored Python code run-python-code can run. Add a kind here when the backend
 * accepts it as a target.
 */
export type PythonCodeRunTargetType = 'python_node' | 'webhook_trigger_node';

/** A saved node, by its backend id: the backend resolves the code it runs (and the node's storage) from it. */
export interface PythonCodeRunTarget {
    type: PythonCodeRunTargetType;
    id: number;
}

export interface RunPythonCodeRequest {
    target: PythonCodeRunTarget;
    variables: Record<string, unknown>;
}

export type PythonCodeExecutionStatus = 'pending' | 'completed' | 'error';

export interface PythonCodeResult {
    execution_id: string;
    status: PythonCodeExecutionStatus;
    result_data: string | null;
    returncode: number | null;
    stderr: string;
    stdout: string;
    created_at?: string;
    finished_at?: string | null;
}

export type PollEvent = { type: 'polling'; attempt: number } | { type: 'result'; data: PythonCodeResult };

@Injectable({ providedIn: 'root' })
export class PythonCodeRunService {
    private headers = new HttpHeaders({ 'Content-Type': 'application/json' });
    private readonly http = inject(HttpClient);
    private readonly configService = inject(ConfigService);

    private get apiUrl(): string {
        return this.configService.apiUrl;
    }

    runPythonCode(payload: RunPythonCodeRequest): Observable<{ execution_id: string }> {
        return this.http.post<{ execution_id: string }>(`${this.apiUrl}run-python-code/`, payload, {
            headers: this.headers,
        });
    }

    getResult(executionId: string): Observable<PythonCodeResult> {
        return this.http.get<PythonCodeResult>(`${this.apiUrl}python-code-result/${executionId}/`);
    }

    getLastTestInput(pythonNodeId: number): Observable<{ detail: string; input: Record<string, string> }> {
        return this.http.get<{ detail: string; input: Record<string, string> }>(
            `${this.apiUrl}pythonnodes/${pythonNodeId}/last-session-input/`
        );
    }

    /**
     * Polls the result of run `executionId` of code whose node allows `executionTimeoutMinutes` per execution,
     * giving up a grace period after that timeout.
     */
    pollResultWithEvents(executionId: string, executionTimeoutMinutes: number): Observable<PollEvent> {
        let attempt = 0;
        let notFoundRetries = 0;

        const poll$: Observable<PollEvent> = timer(POLL_INITIAL_DELAY_MS, POLL_INTERVAL_MS).pipe(
            switchMap(() =>
                this.getResult(executionId).pipe(
                    map((result): PollEvent => {
                        // A successful read means the record exists; reset the create-race counter.
                        notFoundRetries = 0;
                        if (result.status === 'pending') {
                            attempt++;
                            return { type: 'polling', attempt };
                        }
                        return { type: 'result', data: result };
                    }),
                    catchError((error: HttpErrorResponse) => {
                        if (error.status === 404) {
                            notFoundRetries++;
                            if (notFoundRetries <= MAX_NOT_FOUND_RETRIES) {
                                attempt++;
                                return of<PollEvent>({ type: 'polling', attempt });
                            }
                            return throwError(
                                () =>
                                    new Error(
                                        'Execution result not found in the active organization. It may belong to a different organization or have been removed.'
                                    )
                            );
                        }
                        if (error.status === 403) {
                            return throwError(
                                () =>
                                    new Error(
                                        'Access denied. You may lack permission to view this result, or no active organization is selected.'
                                    )
                            );
                        }
                        return throwError(() => error);
                    })
                )
            )
        );

        const deadline$: Observable<PollEvent> = timer(executionTimeoutMinutes * 60_000 + POLL_DEADLINE_GRACE_MS).pipe(
            switchMap(() =>
                throwError(
                    () =>
                        new Error(
                            `No result within ${executionTimeoutMinutes} min (the node's execution timeout) and a grace period. The code may still be running on the server.`
                        )
                )
            )
        );

        return merge(poll$, deadline$).pipe(takeWhile((event) => event.type !== 'result', true));
    }
}
