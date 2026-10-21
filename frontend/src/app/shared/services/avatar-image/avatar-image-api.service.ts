import { HttpClient, HttpContext } from '@angular/common/http';
import { inject, Injectable } from '@angular/core';
import { Observable } from 'rxjs';

import { SKIP_FORBIDDEN_RELOAD } from '../../../core/interceptors/skip-forbidden-reload.context';

@Injectable({
    providedIn: 'root',
})
export class AvatarImageApiService {
    private readonly http = inject(HttpClient);

    /**
     * Avatars sit behind an authenticated endpoint, so they are fetched through HttpClient (which carries the
     * Bearer token) instead of a plain `<img src>`. The URL comes from the backend as-is: an origin-relative,
     * versioned path (`/api/users/<id>/avatar/?v=...`). It therefore only reaches the API when apiUrl is same-origin,
     * which environment.local.example.ts already requires — no prefixing is done here.
     */
    getAvatar(avatarUrl: string): Observable<Blob> {
        // An avatar is decoration: a refusal must fall back to initials, never trigger the permission refresh and
        // page reload that a 403 causes elsewhere.
        const context = new HttpContext().set(SKIP_FORBIDDEN_RELOAD, true);
        return this.http.get(avatarUrl, { responseType: 'blob', context });
    }
}
