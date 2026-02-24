import { ChangeDetectionStrategy, Component, DestroyRef, inject, model, OnInit, signal } from "@angular/core";

import { RagTypeComponent } from "./rag-type/rag-type.component";
import { RAG_TYPES } from "../../../../constants/constants";
import { takeUntilDestroyed } from "@angular/core/rxjs-interop";
import { EmbeddingConfigsService } from "../../../../../settings-dialog/services/embeddings/embedding_configs.service";
import { EmbeddingConfig } from "../../../../../settings-dialog/models/embeddings/embedding-config.model";
import { SelectComponent, SelectItem } from "@shared/components";
import { map } from "rxjs/operators";
import { RagType } from "../../../../models/naive-rag.model";
import { ToastService } from "../../../../../../services/notifications";
import { MATERIAL_FORMS } from "@shared/material-forms";

@Component({
    selector: "app-step-select-rag",
    templateUrl: "./step-select-rag.component.html",
    styleUrls: ["./step-select-rag.component.scss"],
    imports: [
        RagTypeComponent,
        SelectComponent,
        MATERIAL_FORMS
    ],
    changeDetection: ChangeDetectionStrategy.OnPush
})
export class StepSelectRagComponent implements OnInit {
    selectedRag = model<RagType | null>(null);
    embeddingConfigs = signal<SelectItem[]>([]);

    selectedEmbedder = model<number | null>(null);

    private destroyRef = inject(DestroyRef)
    private embeddingConfigService = inject(EmbeddingConfigsService);
    private toastService = inject(ToastService);

    ngOnInit() {
        this.embeddingConfigService.getEmbeddingConfigs()
            .pipe(
                takeUntilDestroyed(this.destroyRef),
                map((configs) => {
                    return configs.map((embedConfig: EmbeddingConfig) => ({
                        name: embedConfig.custom_name,
                        value: embedConfig.id,
                    }))
                })
            )
            .subscribe({
                next: (configs: SelectItem[]) => {
                    this.embeddingConfigs.set(configs);
                },
                error: (error) => {
                    this.toastService.error('Failed to load embedding configs.');
                    console.error('Error loading embedding configs:', error);
                },
            });
    }

    protected readonly RAG_TYPES = RAG_TYPES;
}
