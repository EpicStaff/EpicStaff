import { HttpClient, HttpErrorResponse, HttpHeaders } from '@angular/common/http';
import { inject, Injectable } from '@angular/core';
import { Observable, of, timer } from 'rxjs';
import { catchError, filter, map, switchMap, take, takeWhile, timeout } from 'rxjs/operators';

import { ConfigService } from '../../services/config/config.service';

export interface RunPythonCodeRequest {
    python_code_id: number | null;
    code: string;
    entrypoint: string;
    libraries: string[];
    variables: Record<string, unknown>;
}

export interface PythonCodeResult {
    execution_id: string;
    result_data: string;
    returncode: number;
    stderr: string;
    stdout: string;
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

    pollResult(executionId: string): Observable<PythonCodeResult> {
        return timer(1000, 2000).pipe(
            switchMap(() =>
                this.getResult(executionId).pipe(
                    catchError((error: HttpErrorResponse) => {
                        if (error.status === 404) {
                            return of(null);
                        }
                        throw error;
                    })
                )
            ),
            filter((result): result is PythonCodeResult => result !== null),
            take(1),
            timeout(60000)
        );
    }

    getLastTestInput(pythonNodeId: number): Observable<{ detail: string; input: Record<string, string> }> {
        return this.http.get<{ detail: string; input: Record<string, string> }>(
            `${this.apiUrl}pythonnodes/${pythonNodeId}/last-session-input/`
        );
    }

    pollResultWithEvents(executionId: string): Observable<PollEvent> {
        let attempt = 0;
        return timer(1000, 2000).pipe(
            switchMap(() =>
                this.getResult(executionId).pipe(
                    map((result): PollEvent => ({ type: 'result', data: result })),
                    catchError((error: HttpErrorResponse) => {
                        if (error.status === 404) {
                            attempt++;
                            return of({ type: 'polling' as const, attempt });
                        }
                        throw error;
                    })
                )
            ),
            takeWhile((event) => event.type !== 'result', true),
            timeout(60000)
        );
    }
}
