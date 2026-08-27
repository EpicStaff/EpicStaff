import { forkJoin, Observable, of } from 'rxjs';
import { catchError, map } from 'rxjs/operators';

export type SettledResult<T> = { ok: true; value: T } | { ok: false; error: unknown };

/**
 * `Promise.allSettled` for Observables. Runs every request in parallel and
 * always waits for all of them to finish — one failing request no longer
 * cancels the others (which is what plain `forkJoin` does). The caller can
 * then partition successes vs failures.
 */
export function settleAll<T>(requests: Observable<T>[]): Observable<SettledResult<T>[]> {
    if (requests.length === 0) return of([] as SettledResult<T>[]);
    return forkJoin(
        requests.map((req) =>
            req.pipe(
                map<T, SettledResult<T>>((value) => ({ ok: true, value })),
                catchError((error) => of<SettledResult<T>>({ ok: false, error }))
            )
        )
    );
}

/** Split a list of settled results into successes and failures. */
export function partitionSettled<T>(results: SettledResult<T>[]): {
    successes: T[];
    failures: unknown[];
} {
    const successes: T[] = [];
    const failures: unknown[] = [];
    for (const r of results) {
        if (r.ok) successes.push(r.value);
        else failures.push(r.error);
    }
    return { successes, failures };
}
