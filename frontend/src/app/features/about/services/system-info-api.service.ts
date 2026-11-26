import { HttpClient } from '@angular/common/http';
import { inject, Injectable } from '@angular/core';
import { map, Observable } from 'rxjs';

import { ConfigService } from '../../../services/config';
import { FrontendBuild, SystemInfo } from '../models/system-info.model';

const FRONTEND_BUILD_URL = '/version.json';

/** The shape of `version.json`, written by the frontend image build. */
interface FrontendBuildFile {
    git_sha?: unknown;
    commit_date?: unknown;
}

function textOrNull(value: unknown): string | null {
    return typeof value === 'string' && value !== '' ? value : null;
}

/** HTTP only: the backend's build and feature switches, and the build file the frontend bundle ships with. */
@Injectable({ providedIn: 'root' })
export class SystemInfoApiService {
    private readonly http = inject(HttpClient);
    private readonly configService = inject(ConfigService);

    getSystemInfo(): Observable<SystemInfo> {
        return this.http.get<SystemInfo>(`${this.configService.apiUrl}system-info/`);
    }

    /** Empty strings or missing keys in the file mean the commit is not known. */
    getFrontendBuild(): Observable<FrontendBuild> {
        return this.http
            .get<FrontendBuildFile>(FRONTEND_BUILD_URL)
            .pipe(map((file) => ({ gitSha: textOrNull(file?.git_sha), commitDate: textOrNull(file?.commit_date) })));
    }
}
