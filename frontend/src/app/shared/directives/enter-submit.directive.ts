import { DialogRef } from '@angular/cdk/dialog';
import { DestroyRef, Directive, inject, input, OnInit, output } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';

@Directive({
    selector: '[appEnterSubmit]',
})
export class EnterSubmitDirective implements OnInit {
    readonly appEnterSubmitDisabled = input(false);
    readonly appEnterSubmit = output<void>();

    private readonly dialogRef = inject(DialogRef);
    private readonly destroyRef = inject(DestroyRef);

    ngOnInit(): void {
        this.dialogRef.keydownEvents.pipe(takeUntilDestroyed(this.destroyRef)).subscribe((event: KeyboardEvent) => {
            if (event.key !== 'Enter') return;
            if (event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;
            if (this.appEnterSubmitDisabled()) return;

            const target = event.target;
            if (target instanceof HTMLElement) {
                const tag = target.tagName.toLowerCase();
                if (tag === 'textarea') return;
                if (tag === 'button' || tag === 'a' || tag === 'select') return;
                if (target.isContentEditable) return;
            }

            event.preventDefault();
            this.appEnterSubmit.emit();
        });
    }
}
