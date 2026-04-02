import { Type } from '@angular/core';

import {
    CharacterFormComponent,
    CsvFormComponent,
    HtmlFormComponent,
    JsonFormComponent,
    MarkdownFormComponent,
    TokenFormComponent,
} from '../components/edit-file-parameters-dialog/document-config/strategies-forms';
import { StrategyForm } from '../components/edit-file-parameters-dialog/document-config/strategies-forms/strategy-config-form.abstract';
import { StrategyModel } from '../models/strategy.model';
import { NaiveRagChunkStrategy } from './naive-rag-chunk-strategy';

const asStrategyFormComponent = <T extends StrategyModel>(
    component: Type<StrategyForm<T>>
): Type<StrategyForm<StrategyModel>> => component as unknown as Type<StrategyForm<StrategyModel>>;

export const ADDITIONAL_PARAMS_FORM_COMPONENT_MAP: Record<NaiveRagChunkStrategy, Type<StrategyForm<StrategyModel>>> = {
    markdown: asStrategyFormComponent(MarkdownFormComponent),
    character: asStrategyFormComponent(CharacterFormComponent),
    token: asStrategyFormComponent(TokenFormComponent),
    csv: asStrategyFormComponent(CsvFormComponent),
    json: asStrategyFormComponent(JsonFormComponent),
    html: asStrategyFormComponent(HtmlFormComponent),
};
