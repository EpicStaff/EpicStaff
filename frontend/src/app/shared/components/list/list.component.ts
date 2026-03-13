import {
    ChangeDetectionStrategy,
    Component,
    ContentChild, input,
    TemplateRef
} from "@angular/core";
import { NgTemplateOutlet } from "@angular/common";

@Component({
    selector: 'app-list',
    templateUrl: "./list.component.html",
    styleUrls: ["./list.component.scss"],
    imports: [
        NgTemplateOutlet
    ],
    changeDetection: ChangeDetectionStrategy.OnPush
})
export class ListComponent<T> {
    items = input.required<T[]>();
    width = input<string | null>(null);

    @ContentChild(TemplateRef)
    rowTemplate!: TemplateRef<{
        $implicit: T;
        index: number;
    }>;
}

