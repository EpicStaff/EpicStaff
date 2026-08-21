import { HttpClient, HttpErrorResponse, HttpHeaders } from '@angular/common/http';
import { inject, Injectable } from '@angular/core';
import { merge, Observable, of, throwError, timer } from 'rxjs';
import { catchError, map, switchMap, takeWhile } from 'rxjs/operators';

import { ConfigService } from '../../services/config/config.service';

/** Poll cadence and limits for python-code-result. */
const POLL_INITIAL_DELAY_MS = 1000;
const POLL_INTERVAL_MS = 2000;
const POLL_TIMEOUT_MS = 60000;

const MAX_NOT_FOUND_RETRIES = 3;

export interface RunPythonCodeRequest {
    python_code_id: number | null;
    code: string;
    entrypoint: string;
    libraries: string[];
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

    getPythonCodeId(pythonNodeId: number): Observable<number | null> {
        return this.http
            .get<{ python_code?: { id?: number } | null }>(`${this.apiUrl}pythonnodes/${pythonNodeId}/`)
            .pipe(map((node) => node.python_code?.id ?? null));
    }

    pollResultWithEvents(executionId: string): Observable<PollEvent> {
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

        const deadline$: Observable<PollEvent> = timer(POLL_TIMEOUT_MS).pipe(
            switchMap(() =>
                throwError(
                    () =>
                        new Error('Execution timed out after 60 seconds. The code may still be running on the server.')
                )
            )
        );

        return merge(poll$, deadline$).pipe(takeWhile((event) => event.type !== 'result', true));
    }
}
