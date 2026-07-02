import { ModelTypes } from '@shared/models';

import { LlmLibraryModel } from './llm-library-model.interface';

export interface LlmLibraryProviderGroup {
    id: string;
    providerName: string;
    providerIconPath: string;
    models: LlmLibraryModel[];
    configType: ModelTypes;
}
