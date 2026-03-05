import { Injectable } from '@angular/core';
import { forkJoin, Observable } from 'rxjs';
import { map } from 'rxjs/operators';
import { EmbeddingConfigsService } from './embedding-configs.service';
import { EmbeddingModelsService } from './embeddings.service';
import { GetEmbeddingConfigRequest } from '../shared/models/embedding-config.model';
import { EmbeddingModel } from '../shared/models/embedding.model';

export interface FullEmbeddingConfig extends GetEmbeddingConfigRequest {
  modelDetails: EmbeddingModel | null;
}

@Injectable({
  providedIn: 'root',
})
export class FullEmbeddingConfigService {
  constructor(
    private embeddingConfigService: EmbeddingConfigsService,
    private embeddingModelsService: EmbeddingModelsService
  ) {}

  getFullEmbeddingConfigs(): Observable<FullEmbeddingConfig[]> {
    return forkJoin({
      configs: this.embeddingConfigService.getEmbeddingConfigs(),
      models: this.embeddingModelsService.getEmbeddingModels(),
    }).pipe(
      map(({ configs, models }) => {
        // Create a lookup table mapping model id to model details
        const modelMap: Record<number, EmbeddingModel> = {};
        models.forEach((model) => {
          modelMap[model.id] = model;
        });

        // Filter configs to include only those that are visible
        const visibleConfigs = configs.filter((config) => config.is_visible);

        // Merge each embedding config with its corresponding model details
        return visibleConfigs.map((config) => ({
          ...config,
          modelDetails: modelMap[config.model] || null,
        }));
      })
    );
  }
}
