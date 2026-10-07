import {
    afterRenderEffect,
    Component,
    computed,
    effect,
    ElementRef,
    inject,
    input,
    untracked,
    viewChild,
} from '@angular/core';
import { toSignal } from '@angular/core/rxjs-interop';
import { FormControl, ReactiveFormsModule } from '@angular/forms';
import { Router } from '@angular/router';

import { MAX_QUESTION_LENGTH } from '../../conversations/conversation.model';
import { TranscriptComponent } from '../../conversations/transcript/transcript.component';
import { ChatStore } from '../chat-store.service';

/**
 * `/chat` starts a conversation, `/chat/:id` continues one. After the first question the URL
 * becomes `/chat/<id>`, so a refresh or a copied link reopens the same conversation.
 */
@Component({
    selector: 'app-chat-page',
    imports: [ReactiveFormsModule, TranscriptComponent],
    templateUrl: './chat-page.component.html',
    styleUrl: './chat-page.component.css',
})
export class ChatPageComponent {
    /** Route param `:id` (component input binding). */
    readonly id = input<string>();

    private readonly scroller = viewChild<ElementRef<HTMLElement>>('scroller');

    protected readonly question = new FormControl('', { nonNullable: true });
    private readonly questionText = toSignal(this.question.valueChanges, { initialValue: '' });
    protected readonly store = inject(ChatStore);
    protected readonly canAsk = computed(
        () =>
            this.questionText().trim() !== '' &&
            this.questionText().length <= MAX_QUESTION_LENGTH &&
            !this.store.asking() &&
            !this.store.loading() &&
            this.store.acceptsQuestions()
    );

    private readonly routeEffect = effect(() => {
        const id = this.id();
        untracked(() => (id ? this.store.open(id) : this.store.startNew()));
    });

    private readonly scrollEffect = afterRenderEffect(() => {
        this.store.messages();
        this.store.asking();
        const element = this.scroller()?.nativeElement;
        if (element) element.scrollTop = element.scrollHeight;
    });

    protected readonly maxQuestionLength = MAX_QUESTION_LENGTH;

    private readonly router = inject(Router);

    protected ask(): void {
        if (!this.canAsk()) return;
        const question = this.question.value.trim();
        this.question.setValue('');
        void this.store.ask(question);
        if (!this.id()) {
            // Replace, not push: Back should not return to an empty /chat.
            void this.router.navigate(['/chat', this.store.conversationId()], { replaceUrl: true });
        }
    }

    protected onEnter(event: Event): void {
        const keyboardEvent = event as KeyboardEvent;
        if (keyboardEvent.shiftKey || keyboardEvent.isComposing) return;
        event.preventDefault();
        this.ask();
    }

    protected newConversation(): void {
        this.store.startNew();
        void this.router.navigate(['/chat']);
    }
}
