import { CommonModule } from '@angular/common';
import { ChangeDetectionStrategy, Component, DestroyRef, inject, OnInit } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { LlmConfigStorageService } from '@shared/services';
import { catchError, EMPTY, forkJoin } from 'rxjs';

import { ToastService } from '../../../../services/notifications';
import { DEFAULT_LLMS_SECTIONS } from '../../constants/default-llms-sections.constant';
import { DefaultLlmsCard } from '../../interfaces/default-llms-card.interface';
import { UpdateDefaultModelsRequest } from '../../models/default-models.model';
import { DefaultModelsStorageService } from '../../services/default-models-storage.service';
import { DefaultLlmsCardComponent } from '../default-llms-card/default-llms-card.component';

@Component({
    selector: 'app-default-llms-section',
    imports: [CommonModule, DefaultLlmsCardComponent],
    templateUrl: './default-llms-section.component.html',
    styleUrls: ['./default-llms-section.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class DefaultLlmsSectionComponent implements OnInit {
    private readonly llmConfigStorageService = inject(LlmConfigStorageService);
    private readonly defaultModelsStorageService = inject(DefaultModelsStorageService);
    private readonly destroyRef = inject(DestroyRef);
    private readonly toast = inject(ToastService);

    public readonly sections = DEFAULT_LLMS_SECTIONS;
    public readonly defaultModels = this.defaultModelsStorageService.defaultModels;

    ngOnInit(): void {
        forkJoin([this.llmConfigStorageService.getAllConfigs(), this.defaultModelsStorageService.loadDefaultModels()])
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe();
    }

    public getSelectedConfigId(card: DefaultLlmsCard): number | null {
        const models = this.defaultModels();
        if (!models) return null;
        return models[card.field];
    }

    public onModelSelected(event: { cardId: string; configId: number | null }): void {
        const field = this.findCardField(event.cardId);
        if (!field) return;

        const data: UpdateDefaultModelsRequest = { [field]: event.configId };

        this.defaultModelsStorageService
            .updateDefaultModels(data)
            .pipe(
                takeUntilDestroyed(this.destroyRef),
                catchError(() => {
                    this.toast.error('Failed to update default model.');
                    return EMPTY;
                })
            )
            .subscribe();
    }

    private findCardField(cardId: string): string | null {
        for (const section of this.sections) {
            const card = section.cards.find((c) => c.id === cardId);
            if (card) return card.field;
        }
        return null;
    }
}
