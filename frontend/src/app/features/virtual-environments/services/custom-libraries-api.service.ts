import { HttpClient, HttpParams } from '@angular/common/http';
import { inject, Injectable } from '@angular/core';
import { ActionCode, ResourceCode } from '@shared/models';
import { map, Observable } from 'rxjs';

import { withPermission } from '../../../core/http/permission-context';
import { ConfigService } from '../../../services/config';
import { CustomLibrary, CustomLibraryListResponse, Wheel } from '../models/custom-library.model';

const LIST_LIMIT = '1000';

@Injectable({ providedIn: 'root' })
export class CustomLibrariesApiService {
    private readonly http: HttpClient = inject(HttpClient);
    private readonly configService: ConfigService = inject(ConfigService);

    private get customLibrariesUrl(): string {
        return `${this.configService.apiUrl}custom-libraries/`;
    }

    getCustomLibraries(): Observable<CustomLibrary[]> {
        const params = new HttpParams().set('limit', LIST_LIMIT);
        return this.http
            .get<CustomLibraryListResponse>(this.customLibrariesUrl, {
                params,
                context: withPermission<CustomLibraryListResponse>(ResourceCode.CustomLibraries, ActionCode.Read, {
                    count: 0,
                    limit: 0,
                    offset: 0,
                    next: null,
                    previous: null,
                    result: [],
                }),
            })
            .pipe(map((response) => response.result));
    }

    getCustomLibrary(id: number): Observable<CustomLibrary> {
        return this.http.get<CustomLibrary>(`${this.customLibrariesUrl}${id}/`);
    }

    /** Create a library from its first version: a wheel, which names it at once, or a source
     *  archive, which leaves it unnamed until a background build names it. No name is typed
     *  anywhere. The content type is left to the browser, the only side that knows the multipart
     *  boundary. */
    createCustomLibrary(file: File): Observable<CustomLibrary> {
        const body = new FormData();
        body.append('file', file, file.name);
        return this.http.post<CustomLibrary>(this.customLibrariesUrl, body);
    }

    deleteCustomLibrary(id: number): Observable<void> {
        return this.http.delete<void>(`${this.customLibrariesUrl}${id}/`);
    }

    /** Every version of one library, newest build state included: the list is not paged. */
    getWheels(libraryId: number): Observable<Wheel[]> {
        return this.http.get<Wheel[]>(this.wheelsUrl(libraryId));
    }

    /** Upload a wheel or a source archive as a new version. The content type is left to the
     *  browser, which is the only side that knows the multipart boundary. */
    uploadWheel(libraryId: number, file: File): Observable<Wheel> {
        const body = new FormData();
        body.append('file', file, file.name);
        return this.http.post<Wheel>(this.wheelsUrl(libraryId), body);
    }

    deleteWheel(libraryId: number, wheelId: number): Observable<void> {
        return this.http.delete<void>(`${this.wheelsUrl(libraryId)}${wheelId}/`);
    }

    private wheelsUrl(libraryId: number): string {
        return `${this.customLibrariesUrl}${libraryId}/wheels/`;
    }
}
