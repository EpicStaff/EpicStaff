import { Tag } from '../tag.model';
import { ModelTypes } from './llm-provider.model';

export interface LlmLibraryModel {
    id: number;
    customName: string;
    modelName: string;
    tags: Tag[];
    temperature: number | null; // null = the config has no temperature (voice), so the card shows none
    usedByCount: number | null; // null = "Ready to be used"
    configType: ModelTypes;
    isDeprecated: boolean;
}
