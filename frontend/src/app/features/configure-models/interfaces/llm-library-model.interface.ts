import { ModelTypes, Tag } from '@shared/models';

export interface LlmLibraryModel {
    id: number;
    customName: string;
    modelName: string;
    tags: Tag[];
    temperature: number;
    usedByCount: number | null; // null = "Ready to be used"
    configType: ModelTypes;
}
