import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { forkJoin, Observable, of, throwError } from 'rxjs';
import { catchError, shareReplay, tap } from 'rxjs/operators';

@Injectable({
    providedIn: 'root',
})
export class IconService {
    private cache = new Map<string, Observable<string>>();

    constructor(private http: HttpClient) {}

    getIcon(path: string): Observable<string> {
        if (!this.cache.has(path)) {
            const request$ = this.http.get(path, { responseType: 'text' }).pipe(
                shareReplay(1),
                catchError(error => {
                    this.cache.delete(path);
                    return throwError(() => error);
                })
            );

            this.cache.set(path, request$);
        }
        return this.cache.get(path)!;
    }

    preloadIcons(paths: string[]): Observable<string[]> {
        return forkJoin(paths.map(path => this.getIcon(path)));
    }

    clearCache(): void {
        this.cache.clear();
    }
}
