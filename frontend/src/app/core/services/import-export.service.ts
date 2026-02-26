import { Injectable } from '@angular/core';
import { HttpClient, HttpHeaders } from '@angular/common/http';
import { Observable } from 'rxjs';
import { ConfigService } from '../../services/config/config.service';
import { FlowModel } from '../../visual-programming/core/models/flow.model';

@Injectable({
    providedIn: 'root',
})
export class ImportExportService {
    constructor(
        private http: HttpClient,
        private configService: ConfigService
    ) { }

    private get apiUrl(): string {
        return this.configService.apiUrl + 'graphs/';
    }

    importFlow(file: File): Observable<any> {
        const formData = new FormData();
        formData.append('file', file);

        return this.http.post<any>(`${this.apiUrl}import/`, formData);
    }

    exportFlow(graphId: string): Observable<Blob> {
        return this.http.get(`${this.apiUrl}${graphId}/export/`, {
            responseType: 'blob',
        });
    }

    bulkExportFlow(ids: number[]): Observable<Blob> {
        return this.http.post(`${this.apiUrl}bulk-export/`, { ids }, {
            responseType: 'blob',
        });
    }

}
