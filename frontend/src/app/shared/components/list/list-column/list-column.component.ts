import { Component, input } from "@angular/core";

@Component({
    selector: 'app-list-column',
    template: `
        <div class="list__column"
             [style.width]="width()"
        >
            <ng-content/>
        </div>
    `,
})
export class ListColumnComponent {
    width = input<string | null>(null);
}
