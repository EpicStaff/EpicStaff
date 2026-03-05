import { Injectable } from '@angular/core';
import { forkJoin, Observable } from 'rxjs';
import { map } from 'rxjs/operators';

import { GetLlmConfigRequest } from '../shared/models/llm-config.model';
import { GetLlmModelRequest } from '../shared/models';
import { LLM_Config_Service } from './llm-config.service';
import { LLM_Models_Service } from './llm-models.service';

export interface FullLLMConfig extends GetLlmConfigRequest {
  modelDetails: GetLlmModelRequest | null;
}

@Injectable({
  providedIn: 'root',
})
export class FullLLMConfigService {
  constructor(
    private llmConfigService: LLM_Config_Service,
    private llmModelsService: LLM_Models_Service
  ) {}

  getFullLLMConfigs(): Observable<FullLLMConfig[]> {
    return forkJoin({
      configs: this.llmConfigService.getAllConfigsLLM(),
      models: this.llmModelsService.getLLMModels(),
    }).pipe(
      map(({ configs, models }) => {
        // Create a lookup table mapping model ID to model details.
        const modelMap: Record<number, GetLlmModelRequest> = {};
        models.forEach((model) => {
          modelMap[model.id] = model;
        });

        // Filter LLM configs to include only those marked as visible
        const visibleConfigs = configs.filter((config) => config.is_visible);

        // Merge each config with its corresponding model details.
        return visibleConfigs.map((config) => ({
          ...config,
          modelDetails: modelMap[config.model] || null, // Attach model details or null if not found
        }));
      })
    );
  }
}
