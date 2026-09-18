import { HttpClient } from '@angular/common/http';
import { inject, Injectable } from '@angular/core';
import { Observable } from 'rxjs';

import { CombinedSurface } from '../../features/agent-definitions/models/surface.model';
import { ConfigService } from '../../services/config/config.service';

@Injectable({ providedIn: 'root' })
export class NodeSurfaceCombineApiService {
    private readonly http: HttpClient = inject(HttpClient);
    private readonly configService: ConfigService = inject(ConfigService);

    private get apiUrl(): string {
        return this.configService.apiUrl;
    }

    combineAgentNode(id: number): Observable<CombinedSurface> {
        return this.http.get<CombinedSurface>(`${this.apiUrl}agentnodes/${id}/combine/`);
    }

    combineTaskNode(id: number): Observable<CombinedSurface> {
        return this.http.get<CombinedSurface>(`${this.apiUrl}tasknodes/${id}/combine/`);
    }
}
