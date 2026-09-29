import { ChangeDetectionStrategy, Component, input, output, signal } from '@angular/core';

@Component({
    selector: 'app-inputs-you-can-use',
    templateUrl: './inputs-you-can-use.component.html',
    styleUrls: ['./inputs-you-can-use.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class InputsYouCanUseComponent {
    readonly names = input<string[]>([]);
    readonly insert = output<string>();

    readonly open = signal<boolean>(true);

    toggle(): void {
        this.open.update((v) => !v);
    }
}
