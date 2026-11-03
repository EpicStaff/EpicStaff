import { Component, computed, input } from '@angular/core';
import { humanizeErrorMessage } from '@shared/utils';

/**
 * The red bar a dialog shows when the server refuses a save, e.g. a 400 naming the field and the permission it
 * needs. Hidden while there is no message, so a dialog can keep it in place and only set or clear the text. The
 * message is shown as a sentence: its leading API field label is turned into words (see humanizeErrorMessage).
 */
@Component({
    selector: 'app-error-banner',
    template: '{{ text() }}',
    styleUrls: ['./error-banner.component.scss'],
    host: {
        role: 'alert',
        '[hidden]': '!text()',
    },
})
export class ErrorBannerComponent {
    readonly message = input<string | null>(null);

    protected readonly text = computed(() => humanizeErrorMessage(this.message()));
}
