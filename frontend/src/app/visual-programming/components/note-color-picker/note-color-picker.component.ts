import { Overlay, OverlayModule, OverlayPositionBuilder, OverlayRef } from '@angular/cdk/overlay';
import { TemplatePortal } from '@angular/cdk/portal';
import {
    ChangeDetectionStrategy,
    Component,
    DestroyRef,
    ElementRef,
    inject,
    input,
    output,
    signal,
    TemplateRef,
    viewChild,
    ViewContainerRef,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';

import { NOTE_COLORS } from '../../core/utils/note-colors.util';

@Component({
    selector: 'app-note-color-picker',
    imports: [OverlayModule],
    templateUrl: './note-color-picker.component.html',
    styleUrls: ['./note-color-picker.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class NoteColorPickerComponent {
    readonly color = input<string>(NOTE_COLORS[0]);
    readonly colorChange = output<string>();

    protected readonly colors = NOTE_COLORS;
    protected readonly open = signal(false);

    private readonly triggerButton = viewChild.required<ElementRef<HTMLButtonElement>>('triggerButton');
    private readonly dropdownTemplate = viewChild.required<TemplateRef<unknown>>('dropdownTemplate');

    private readonly overlay = inject(Overlay);
    private readonly overlayPositionBuilder = inject(OverlayPositionBuilder);
    private readonly viewContainerRef = inject(ViewContainerRef);
    private readonly destroyRef = inject(DestroyRef);

    private overlayRef: OverlayRef | null = null;

    protected toggle(): void {
        this.open() ? this.close() : this.openDropdown();
    }

    protected selectColor(color: string): void {
        this.colorChange.emit(color);
        this.close();
    }

    private openDropdown(): void {
        const origin = this.triggerButton().nativeElement;

        const positionStrategy = this.overlayPositionBuilder
            .flexibleConnectedTo(origin)
            .withPositions([
                { originX: 'start', originY: 'bottom', overlayX: 'start', overlayY: 'top', offsetY: 4 },
                { originX: 'start', originY: 'top', overlayX: 'start', overlayY: 'bottom', offsetY: -4 },
            ])
            .withPush(false);

        this.overlayRef = this.overlay.create({
            positionStrategy,
            scrollStrategy: this.overlay.scrollStrategies.reposition(),
            hasBackdrop: true,
            backdropClass: 'transparent-backdrop',
        });

        this.overlayRef
            .backdropClick()
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe(() => this.close());

        const portal = new TemplatePortal(this.dropdownTemplate(), this.viewContainerRef);
        this.overlayRef.attach(portal);
        this.open.set(true);
    }

    private close(): void {
        if (this.overlayRef) {
            this.overlayRef.detach();
            this.overlayRef.dispose();
            this.overlayRef = null;
        }
        this.open.set(false);
    }
}
