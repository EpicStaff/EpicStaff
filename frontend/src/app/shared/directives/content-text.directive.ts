import { afterNextRender, DestroyRef, Directive, ElementRef, inject, NgZone, signal } from '@angular/core';

/**
 * The text its element shows, whitespace collapsed, kept current as the content changes. For a component that names
 * itself (a tooltip, an aria-label) after the label its caller projects into it:
 * `<span appContentText #label="appContentText"><ng-content /></span>` … `[matTooltip]="label.text()"`.
 */
@Directive({
    selector: '[appContentText]',
    exportAs: 'appContentText',
})
export class ContentTextDirective {
    private readonly currentText = signal('');
    readonly text = this.currentText.asReadonly();

    private readonly element = inject<ElementRef<HTMLElement>>(ElementRef).nativeElement;
    private readonly ngZone = inject(NgZone);
    private readonly destroyRef = inject(DestroyRef);

    constructor() {
        afterNextRender(() => {
            this.readText();
            // Watched outside Angular: most mutations in a button (an icon, a class) leave its text alone and are no
            // reason for change detection. A changed text sets the signal, which schedules it.
            const observer = this.ngZone.runOutsideAngular(() => {
                const mutationObserver = new MutationObserver(() => this.readText());
                mutationObserver.observe(this.element, { characterData: true, childList: true, subtree: true });
                return mutationObserver;
            });
            this.destroyRef.onDestroy(() => observer.disconnect());
        });
    }

    private readText(): void {
        const text = (this.element.textContent ?? '').replace(/\s+/g, ' ').trim();
        if (text !== this.currentText()) this.currentText.set(text);
    }
}
