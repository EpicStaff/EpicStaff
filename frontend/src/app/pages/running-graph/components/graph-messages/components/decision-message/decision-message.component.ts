import { CommonModule } from '@angular/common';
import { ChangeDetectionStrategy, Component, computed, DestroyRef, inject, Input, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';

import { AppSvgIconComponent } from '../../../../../../shared/components/app-svg-icon/app-svg-icon.component';
import { GraphMessage, WaitForDecisionMessageData } from '../../../../models/graph-session-message.model';
import { DecisionAnswerRequest, DecisionAnswerService } from '../../../../services/decision-answer.service';

@Component({
    selector: 'app-decision-message',
    standalone: true,
    imports: [CommonModule, AppSvgIconComponent],
    templateUrl: './decision-message.component.html',
    styleUrls: ['./decision-message.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class DecisionMessageComponent {
    @Input() message!: GraphMessage;
    @Input() sessionId: string | null = null;

    readonly selectedOptionIndex = signal<number | null>(null);
    readonly freeText = signal<string>('');
    readonly isSubmitting = signal<boolean>(false);
    readonly isAnswered = signal<boolean>(false);
    readonly errorMessage = signal<string | null>(null);

    readonly submittedOptionIndex = signal<number | null>(null);
    readonly submittedFreeText = signal<string | null>(null);

    get data(): WaitForDecisionMessageData | null {
        if (this.message?.message_data?.message_type === 'wait_for_decision') {
            return this.message.message_data as WaitForDecisionMessageData;
        }
        return null;
    }

    readonly canSubmit = computed(() => {
        const optionSelected = this.selectedOptionIndex() !== null;
        const hasFreeText = this.freeText().trim().length > 0;
        const allowFreeText = this.data?.allow_free_text ?? false;
        return optionSelected || (allowFreeText && hasFreeText);
    });

    private readonly decisionAnswerService = inject(DecisionAnswerService);
    private readonly destroyRef = inject(DestroyRef);

    selectOption(index: number): void {
        if (this.isSubmitting() || this.isAnswered()) return;
        this.selectedOptionIndex.set(this.selectedOptionIndex() === index ? null : index);
        this.errorMessage.set(null);
    }

    onFreeTextChange(event: Event): void {
        const target = event.target as HTMLTextAreaElement;
        this.freeText.set(target.value);
        this.errorMessage.set(null);
    }

    submit(): void {
        if (this.isSubmitting() || this.isAnswered()) return;
        if (!this.canSubmit()) return;

        if (!this.sessionId) {
            this.errorMessage.set('No active session available; cannot submit decision.');
            return;
        }

        const data = this.data;
        if (!data) return;

        const optionIndex = this.selectedOptionIndex();
        const rawFreeText = this.freeText().trim();
        const freeText = data.allow_free_text && rawFreeText.length > 0 ? rawFreeText : null;

        const payload: DecisionAnswerRequest = {
            decision_id: data.decision_id,
            option_index: optionIndex,
            free_text: freeText,
        };

        this.isSubmitting.set(true);
        this.errorMessage.set(null);

        this.decisionAnswerService
            .submitDecisionAnswer(this.sessionId, payload)
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe({
                next: () => {
                    this.submittedOptionIndex.set(optionIndex);
                    this.submittedFreeText.set(freeText);
                    this.isAnswered.set(true);
                    this.isSubmitting.set(false);
                },
                error: (error) => {
                    console.error('Failed to submit decision answer:', error);
                    this.errorMessage.set('Failed to submit your decision. Please try again.');
                    this.isSubmitting.set(false);
                },
            });
    }
}
