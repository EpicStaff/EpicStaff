import { Directive, HostListener, inject, input, output, signal } from '@angular/core';
import { ActionCode, ResourceCode } from '@shared/models';

import { PermissionsService } from '../../services/auth/permissions.service';

/**
 * Turns any host element into a label drop target.
 * Emits `labelDropped` with the label id when a valid drag ends on the host.
 * Exposes `isDragOver` so the host template can apply visual feedback.
 * Pass `resourceCode` to gate drops behind the Update permission.
 */
@Directive({
    selector: '[appLabelDrop]',
    exportAs: 'appLabelDrop',
})
export class LabelDropDirective {
    readonly resourceCode = input<ResourceCode | undefined>(undefined);
    readonly labelDropped = output<number>();
    readonly isDragOver = signal<boolean>(false);

    private readonly permissions = inject(PermissionsService);

    private canDrop(): boolean {
        const resource = this.resourceCode();
        if (!resource) return true;
        return this.permissions.can(resource, ActionCode.Update);
    }

    @HostListener('dragover', ['$event'])
    onDragOver(event: DragEvent): void {
        if (!this.canDrop()) return;
        if (!event.dataTransfer?.types.includes('application/x-label-id')) return;
        event.preventDefault();
        event.stopPropagation();
        this.isDragOver.set(true);
    }

    @HostListener('dragleave', ['$event'])
    onDragLeave(event: DragEvent): void {
        const related = event.relatedTarget as Node | null;
        const el = event.currentTarget as HTMLElement;
        if (related && el.contains(related)) return;
        this.isDragOver.set(false);
    }

    @HostListener('drop', ['$event'])
    onDrop(event: DragEvent): void {
        if (!this.canDrop()) return;
        event.preventDefault();
        event.stopPropagation();
        this.isDragOver.set(false);
        const raw = event.dataTransfer?.getData('application/x-label-id');
        if (!raw) return;
        const id = Number(raw);
        if (!Number.isFinite(id)) return;
        this.labelDropped.emit(id);
    }
}
