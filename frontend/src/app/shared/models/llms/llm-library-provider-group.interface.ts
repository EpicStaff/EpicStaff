import { LlmLibraryModel } from './llm-library-model.interface';
import { ModelTypes } from './llm-provider.model';

export interface LlmLibraryProviderGroup {
    id: string;
    providerName: string;
    providerIconPath: string;
    models: LlmLibraryModel[];
    configType: ModelTypes;
}
