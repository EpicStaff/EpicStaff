import { CommonModule } from '@angular/common';
import {
    ChangeDetectionStrategy,
    Component,
    computed,
    DestroyRef,
    inject,
    OnInit,
    output,
    signal,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { FormControl, FormGroup, ReactiveFormsModule } from '@angular/forms';
import { GetLlmConfigRequest } from '@shared/models';

import { AppSvgIconComponent } from '../../../../shared/components/app-svg-icon/app-svg-icon.component';
import { LlmConfigStorageService } from '../../../../shared/services/llms/llm-config-storage.service';
import { FlowAssistantService } from '../../flow-assistant.service';

@Component({
    selector: 'app-flow-assistant-settings',
    standalone: true,
    imports: [CommonModule, ReactiveFormsModule, AppSvgIconComponent],
    templateUrl: './flow-assistant-settings.component.html',
    styleUrls: ['./flow-assistant-settings.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class FlowAssistantSettingsComponent implements OnInit {
    // 1. Inputs / Outputs
    readonly closed = output<void>();

    // 3. Signals & Computed
    readonly llmConfigs = signal<GetLlmConfigRequest[]>([]);
    readonly isLoadingConfigs = signal(false);
    readonly isSaving = signal(false);

    readonly config = computed(() => this.assistantService.config());

    // 5. Public template-bound
    readonly form = new FormGroup({
        llm_config: new FormControl<number | null>(null),
    });

    // 6. Private fields
    private readonly assistantService = inject(FlowAssistantService);
    private readonly llmConfigStorage = inject(LlmConfigStorageService);
    private readonly destroyRef = inject(DestroyRef);

    ngOnInit(): void {
        this.loadLlmConfigs();

        const cfg = this.config();
        if (cfg) {
            this.form.patchValue({
                llm_config: cfg.llm_config,
            });
        }

        this.form.markAsPristine();
    }

    get isDirty(): boolean {
        return this.form.dirty;
    }

    save(): void {
        if (!this.isDirty || this.isSaving()) return;

        this.isSaving.set(true);
        const value = this.form.getRawValue();

        const graphId = this.assistantService.currentGraphId();
        if (!graphId) {
            this.isSaving.set(false);
            return;
        }

        this.assistantService.updateConfig({
            llm_config: value.llm_config ?? null,
        });

        this.form.markAsPristine();
        this.isSaving.set(false);
        this.closed.emit();
    }

    closePanel(): void {
        this.closed.emit();
    }

    private loadLlmConfigs(): void {
        this.isLoadingConfigs.set(true);
        this.llmConfigStorage
            .getAllConfigs()
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe({
                next: (configs) => {
                    this.llmConfigs.set(configs);
                    this.isLoadingConfigs.set(false);
                },
                error: () => {
                    this.isLoadingConfigs.set(false);
                },
            });
    }
}
