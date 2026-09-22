import { ChangeDetectionStrategy, Component, inject, input } from '@angular/core';
import { DomSanitizer, SafeHtml } from '@angular/platform-browser';
import { AppIconComponent, AppSvgIconComponent } from '@shared/components';

import { getIconForEntityType, getSpriteIcon, isInlineSvgIcon } from '../../utils/entity-icon.util';

@Component({
    selector: 'app-entity-icon',
    imports: [AppIconComponent, AppSvgIconComponent],
    templateUrl: './entity-icon.component.html',
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class EntityIconComponent {
    private readonly sanitizer = inject(DomSanitizer);

    public readonly entityType = input.required<string>();
    public readonly color = input<string>('');
    public readonly size = input<string>('1.25rem');

    protected readonly getSpriteIcon = getSpriteIcon;
    protected readonly isInlineSvgIcon = isInlineSvgIcon;

    protected get iconPath(): string {
        return getIconForEntityType(this.entityType());
    }

    protected get inlineSvg(): SafeHtml {
        return this.sanitizer.bypassSecurityTrustHtml(this.iconPath);
    }
}
