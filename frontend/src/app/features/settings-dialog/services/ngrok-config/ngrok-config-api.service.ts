import { HttpClient } from "@angular/common/http";
import { inject, Injectable } from "@angular/core";
import { ApiGetResponse } from '../../../transcription/services/transcription-models.service';
import { map, Observable } from "rxjs";
import { ConfigService } from "../../../../services/config";
import { CreateNgrokConfigRequest, GetNgrokConfigResponse } from "../../models/ngrok-config.model";

@Injectable({
    providedIn: 'root',
})
export class NgrokConfigApiService {
    private configService = inject(ConfigService);
    private http = inject(HttpClient);

    private get apiUrl(): string {
        return this.configService.apiUrl + 'ngrok-config/';
    }

    createNgrokConfig(dto: CreateNgrokConfigRequest): Observable<GetNgrokConfigResponse> {
        return this.http.post<GetNgrokConfigResponse>(this.apiUrl, dto);
    }

    getNgrokConfigs(): Observable<GetNgrokConfigResponse[]> {
        return this.http.get<ApiGetResponse<GetNgrokConfigResponse>>(this.apiUrl)
            .pipe(map((response) => response.results));
    }

    getNgrokConfigById(id: number): Observable<GetNgrokConfigResponse> {
        return this.http.get<GetNgrokConfigResponse>(this.apiUrl + id + '/');
    }

    updateNgrokConfig(id: number, dto: Partial<CreateNgrokConfigRequest>): Observable<GetNgrokConfigResponse> {
        return this.http.put<GetNgrokConfigResponse>(this.apiUrl + id + '/', dto);
    }

    deleteNgrokConfig(id: number): Observable<void> {
        return this.http.delete<void>(this.apiUrl + id + '/');
    }
}
