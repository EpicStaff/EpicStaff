import { Dialog } from '@angular/cdk/dialog';
import {
    AfterViewInit,
    ChangeDetectionStrategy,
    Component,
    computed,
    effect,
    ElementRef,
    inject,
    input,
    OnDestroy,
    OnInit,
    output,
    signal,
    viewChild,
} from '@angular/core';
import { FormsModule } from '@angular/forms';
import { AppSvgIconComponent, ButtonComponent, LlmModelConfigDialogComponent } from '@shared/components';
import { HasPermissionDirective } from '@shared/directives';
import { ActionCode, ResourceCode } from '@shared/models';
import { FullLLMConfig, FullLLMConfigService } from '@shared/services';
import { Subject } from 'rxjs';
import { finalize, takeUntil } from 'rxjs/operators';

import { MergedConfig } from '../../../../../features/staff/services/full-agent.service';
import { LlmItemComponent } from './llm-item/llm-item.component';

@Component({
    selector: 'app-llm-popup',
    imports: [FormsModule, LlmItemComponent, AppSvgIconComponent, ButtonComponent, HasPermissionDirective],
    templateUrl: './llm-popup.component.html',
    styleUrls: ['./llm-popup.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class LLMPopupComponent implements OnInit, OnDestroy, AfterViewInit {
    public readonly cellValue = input<MergedConfig[]>([]);

    public readonly configsSelected = output<MergedConfig[]>();
    public readonly cancel = output<void>();

    private readonly searchInput = viewChild<ElementRef<HTMLInputElement>>('searchInput');

    private readonly fullLLMConfigService = inject(FullLLMConfigService);
    private readonly dialog = inject(Dialog);

    public readonly searchTerm = signal<string>('');
    public readonly loading = signal<boolean>(true);

    public readonly llmConfigs = this.fullLLMConfigService.fullLLMConfigs;

    public readonly selectedLLMId = signal<number | null>(null);

    public readonly selectedLLM = computed<FullLLMConfig | null>(() => {
        const id = this.selectedLLMId();
        if (id == null) return null;
        return this.llmConfigs().find((c) => c.id === id) ?? null;
    });

    public readonly filteredLLMs = computed<MergedConfig[]>(() => {
        const configs: MergedConfig[] = this.llmConfigs().map((config) => ({
            id: config.id,
            custom_name: config.custom_name,
            model_name: config.modelDetails?.name || 'Unknown Model',
            type: 'llm',
            provider_id: config.modelDetails?.llm_provider,
            provider_name: config.providerDetails?.name || 'Unknown Provider',
        }));
        const term = this.searchTerm().toLowerCase();
        if (!term) return configs;
        return configs.filter(
            (c) => c.model_name.toLowerCase().includes(term) || (c.custom_name ?? '').toLowerCase().includes(term)
        );
    });

    private readonly destroyed$ = new Subject<void>();

    constructor() {
        effect(() => {
            const cell = this.cellValue();
            const llmConfigs = this.llmConfigs();
            if (!cell || cell.length === 0) return;

            const llmMatch = cell.find((c) => c.type === 'llm');
            if (llmMatch && llmConfigs.some((c) => c.id === llmMatch.id)) {
                this.selectedLLMId.set(llmMatch.id);
            }
        });
    }

    public ngOnInit(): void {
        this.loadConfigs();
    }

    public ngAfterViewInit(): void {
        this.searchInput()?.nativeElement.focus();
    }

    public ngOnDestroy(): void {
        this.destroyed$.next();
        this.destroyed$.complete();
    }

    private loadConfigs(): void {
        this.loading.set(true);

        this.fullLLMConfigService
            .getFullLLMConfigs()
            .pipe(
                takeUntil(this.destroyed$),
                finalize(() => this.loading.set(false))
            )
            .subscribe();
    }

    public onSelectLLM(item: MergedConfig): void {
        this.selectedLLMId.update((current) => (current === item.id ? null : item.id));
    }

    public onSave(): void {
        const selectedConfigs: MergedConfig[] = [];

        const llm = this.selectedLLM();
        if (llm) {
            selectedConfigs.push({
                id: llm.id,
                custom_name: llm.custom_name,
                model_name: llm.modelDetails?.name || 'Unknown Model',
                type: 'llm',
                provider_id: llm.modelDetails?.llm_provider,
                provider_name: llm.providerDetails?.name || 'Unknown Provider',
            });
        }

        this.configsSelected.emit(selectedConfigs);
    }

    public onCancel(): void {
        this.cancel.emit();
    }

    public onCreateLlmModel(): void {
        this.dialog.open(LlmModelConfigDialogComponent, {
            height: '90vh',
            width: '600px',
        });
    }

    protected readonly ResourceCode = ResourceCode;
    protected readonly ActionCode = ActionCode;
}
