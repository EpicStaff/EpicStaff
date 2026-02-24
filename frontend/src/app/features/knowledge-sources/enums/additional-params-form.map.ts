import { Type } from "@angular/core";
import {
    MarkdownFormComponent,
    CharacterFormComponent,
    TokenFormComponent,
    CsvFormComponent,
    JsonFormComponent,
    HtmlFormComponent
} from "../components/edit-file-parameters-dialog/document-config/strategies-forms";
import {
    StrategyForm
} from "../components/edit-file-parameters-dialog/document-config/strategies-forms/strategy-config-form.abstract";
import { NaiveRagChunkStrategy } from "./naive-rag-chunk-strategy";

export const ADDITIONAL_PARAMS_FORM_COMPONENT_MAP: Record<NaiveRagChunkStrategy, Type<StrategyForm<any>>> = {
    markdown: MarkdownFormComponent,
    character: CharacterFormComponent,
    token: TokenFormComponent,
    csv: CsvFormComponent,
    json: JsonFormComponent,
    html: HtmlFormComponent,
};
