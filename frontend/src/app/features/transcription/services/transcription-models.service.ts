import { HttpClient, HttpHeaders } from '@angular/common/http';
import { Injectable } from '@angular/core';
import { map, Observable, of, shareReplay, switchMap } from 'rxjs';
import { ConfigService } from '../../../services/config/config.service';
import { GetRealtimeTranscriptionModelRequest } from '../models/transcription-config.model';

export interface ApiGetResponse<T> {
  count: number;
  next: string | null;
  previous: string | null;
  results: T[];
}

@Injectable({
  providedIn: 'root',
})
export class RealtimeTranscriptionModelsService {
  private headers = new HttpHeaders({ 'Content-Type': 'application/json' });

  // Property to hold the cached observable
  private models$!: Observable<GetRealtimeTranscriptionModelRequest[]>;

  constructor(private http: HttpClient, private configService: ConfigService) {
    // Initialize the models cache in the constructor
    this.initializeModelsCache();
  }

  // Dynamically retrieve the API URL from ConfigService
  private get apiUrl(): string {
    return this.configService.apiUrl + 'realtime-transcription-models/';
  }

  // Initialize the cache
  private initializeModelsCache(): void {
    this.models$ = this.http
      .get<ApiGetResponse<GetRealtimeTranscriptionModelRequest>>(this.apiUrl, {
        headers: this.headers,
      })
      .pipe(
        map((response) => response.results),
        shareReplay(1)
      );
  }

  /**
   * Gets all realtime transcription models, fetching from API only on first call
   * and returning cached data for subsequent calls
   */
  getAllModels(): Observable<ApiGetResponse<GetRealtimeTranscriptionModelRequest>> {
    return this.http
      .get<ApiGetResponse<GetRealtimeTranscriptionModelRequest>>(this.apiUrl)
  }

  /**
   * Force refresh the models cache
   */
  refreshModels(): Observable<GetRealtimeTranscriptionModelRequest[]> {
    this.initializeModelsCache();
    return this.models$;
  }

  /**
   * Get a specific realtime transcription model by ID.
   * First tries to find it in the cached models,
   * falls back to API call if not found.
   */
  getModelById(id: number): Observable<GetRealtimeTranscriptionModelRequest> {
    return this.models$.pipe(
      switchMap((models) => {
        // Try to find the model in the cache first
        const cachedModel = models.find((model) => model.id === id);

        if (cachedModel) {
          return of(cachedModel);
        }

        // If not found in cache, fetch from API
        return this.http.get<GetRealtimeTranscriptionModelRequest>(
          `${this.apiUrl}${id}/`,
          {
            headers: this.headers,
          }
        );
      })
    );
  }
}
