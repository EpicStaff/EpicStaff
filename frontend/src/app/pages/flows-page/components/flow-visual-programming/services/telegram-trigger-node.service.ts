import {HttpClient, HttpHeaders} from "@angular/common/http";
import {ConfigService} from "../../../../../services/config/config.service";
import {ApiGetRequest} from "../../../../../core/models/api-request.model";
import {map, Observable} from "rxjs";
import {
    CreateTelegramTriggerNodeRequest,
    GetTelegramTriggerNodeRequest
} from "../models/telegram-trigger.model";
import {Injectable} from "@angular/core";

@Injectable({
    providedIn: 'root',
})
export class TelegramTriggerNodeService {
    private headers = new HttpHeaders({
        'Content-Type': 'application/json',
    });

    constructor(private http: HttpClient, private configService: ConfigService) { }

    private get apiUrlTriggerFields(): string {
        return this.configService.apiUrl + 'telegram-trigger-available-fields/';
    }

    private get apiUrlNodeFields(): string {
        return this.configService.apiUrl + 'telegram-trigger-node-fields/';
    }

    private get apiUrlNode(): string {
        return this.configService.apiUrl + 'telegram-trigger-nodes/';
    }

    getTelegramTriggerNodes(): Observable<GetTelegramTriggerNodeRequest[]> {
        return this.http.get<ApiGetRequest<GetTelegramTriggerNodeRequest>>(this.apiUrlNode)
            .pipe(
                map((response) => {
                    return response.results.sort((a, b) => b.id - a.id);
                })
            );
    }

    createTelegramTriggerNode(request: CreateTelegramTriggerNodeRequest): Observable<GetTelegramTriggerNodeRequest> {
        return this.http.post<GetTelegramTriggerNodeRequest>(this.apiUrlNode, request, {
            headers: this.headers,
        });
    }

    updateTelegramTriggerNode(
        id: number,
        request: CreateTelegramTriggerNodeRequest
    ): Observable<GetTelegramTriggerNodeRequest> {
        return this.http.put<GetTelegramTriggerNodeRequest>(
            `${this.apiUrlNode}${id}/`,
            request,
            {
                headers: this.headers,
            }
        );
    }

    deleteTelegramTriggerNode(id: number): Observable<void> {
        return this.http.delete<void>(`${this.apiUrlNode}${id}/`, {
            headers: this.headers,
        });
    }
}
