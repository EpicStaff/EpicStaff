import { NgComponentOutlet } from "@angular/common";
import {
    ChangeDetectionStrategy,
    Component, computed,
    input, OnChanges,
    signal, SimpleChanges,
} from "@angular/core";
import { MATERIAL_FORMS } from "@shared/material-forms";
import { SelectComponent } from "@shared/components";
import { CHUNK_STRATEGIES_SELECT_ITEMS } from "../../../constants/constants";

import { FormGroup, ReactiveFormsModule } from "@angular/forms";
import { ADDITIONAL_PARAMS_FORM_COMPONENT_MAP } from "../../../enums/additional-params-form.map";
import { NaiveRagChunkStrategy } from "../../../enums/naive-rag-chunk-strategy";
import { TableDocument } from "../../rag-configuration/configuration-table/configuration-table.interface";

@Component({
    selector: 'app-document-config',
    templateUrl: './document-config.component.html',
    styleUrls: ['./document-config.component.scss'],
    imports: [
        MATERIAL_FORMS,
        SelectComponent,
        ReactiveFormsModule,
        NgComponentOutlet,
    ],
    changeDetection: ChangeDetectionStrategy.OnPush
})
export class DocumentConfigComponent implements OnChanges {
    document = input.required<TableDocument>();
    ragId = input.required<number>();

    selectedStrategy = signal<NaiveRagChunkStrategy | null>(null);

    private additionalFormParams = computed(() => {
        const document = this.document();
        const additionalParams = document.additional_params;

        switch (this.selectedStrategy()) {
            case 'markdown':
                return {
                    chunk_size: document.chunk_size,
                    chunk_overlap: document.chunk_overlap,
                    headers_to_split_on: [],
                    return_each_line: true,
                    strip_headers: false,
                };
            case 'character':
                return {
                    chunk_size: document.chunk_size,
                    chunk_overlap: document.chunk_overlap,
                    regex: additionalParams['character']?.regex,
                };
            case 'csv':
                return {
                    rows_in_chunk: additionalParams['csv']?.rows_in_chunk,
                    headers_level: additionalParams['csv']?.headers_level,
                };
            case 'json':
                return {
                    chunk_size: document.chunk_size,
                    chunk_overlap: document.chunk_overlap,
                }
            case 'html':
                return {
                    chunk_size: document.chunk_size,
                    chunk_overlap: document.chunk_overlap,
                    preserve_links: additionalParams['html']?.preserve_links,
                    normalize_text: additionalParams['html']?.normalize_text,
                    external_metadata: additionalParams['html']?.external_metadata,
                    denylist_tags: additionalParams['html']?.denylist_tags,
                }
            case 'token':
                return {
                    chunk_size: document.chunk_size,
                    chunk_overlap: document.chunk_overlap,
                }
            default:
                return;
        }
    });
    formComponent = computed(() => {
        const strategy = this.selectedStrategy();
        if (!strategy) return null;

        return ADDITIONAL_PARAMS_FORM_COMPONENT_MAP[strategy];
    });
    componentInputs = computed(() => ({
        parentForm: this.form,
        params: this.additionalFormParams(),
    }));

    form: FormGroup = new FormGroup({});

    ngOnChanges(changes: SimpleChanges) {
        const strategy = this.document().chunk_strategy;
        this.selectedStrategy.set(strategy);
    }

    protected readonly chunkStrategySelectItems = CHUNK_STRATEGIES_SELECT_ITEMS;
}
