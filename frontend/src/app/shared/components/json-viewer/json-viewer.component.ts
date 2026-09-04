import { ChangeDetectionStrategy, Component, Input, OnChanges } from '@angular/core';

interface Segment {
    key: string;
    value: unknown;
    type: SegmentType;
    description: string;
    expanded: boolean;
}

type SegmentType =
    | 'string'
    | 'number'
    | 'boolean'
    | 'null'
    | 'undefined'
    | 'array'
    | 'object'
    | 'date'
    | 'function'
    | 'unknown';

@Component({
    selector: 'app-json-viewer',
    imports: [],
    template: `
        <section class="json-viewer">
            @for (segment of segments; track segment.key) {
                <section class="segment segment-type-{{ segment.type }}">
                    <section
                        class="segment-main"
                        [class.expandable]="isExpandable(segment)"
                        [class.expanded]="segment.expanded"
                        (click)="toggle(segment)"
                    >
                        @if (isExpandable(segment)) {
                            <div class="toggler"></div>
                        }
                        <span class="segment-key">{{ segment.key }}</span>
                        <span class="segment-separator">: </span>
                        @if (!segment.expanded || !isExpandable(segment)) {
                            <span class="segment-value">{{ segment.description }}</span>
                        }
                    </section>
                    @if (segment.expanded && isExpandable(segment)) {
                        <section class="children">
                            <app-json-viewer
                                [json]="segment.value"
                                [expanded]="expanded"
                            />
                        </section>
                    }
                </section>
            }
        </section>
    `,
    styles: [
        `
            .json-viewer {
                position: relative;
                width: 100%;
                height: 100%;
                overflow: hidden;
                font-family: monospace;
                font-size: 1em;
            }

            .segment {
                padding: 2px;
                margin: 1px 1px 1px 12px;
            }

            .segment-main {
                word-wrap: break-word;
            }

            .segment-type-object > .segment-main,
            .segment-type-array > .segment-main {
                white-space: nowrap;
            }

            .toggler {
                position: absolute;
                margin-top: 3px;
                margin-left: -14px;
                font-size: 0.8em;
                line-height: 1.2em;
                color: #787878;
                vertical-align: middle;
            }

            .toggler::after {
                display: inline-block;
                content: '\\25ba';
                transition: transform 0.1s ease-in;
            }

            .expanded > .toggler::after {
                transform: rotate(90deg);
            }

            .expandable,
            .expandable > .toggler {
                cursor: pointer;
            }

            .children {
                margin-left: 12px;
            }
        `,
    ],
    changeDetection: ChangeDetectionStrategy.Eager,
})
export class JsonViewerComponent implements OnChanges {
    @Input() public json: unknown;
    @Input() public expanded = true;

    public segments: Segment[] = [];

    public ngOnChanges(): void {
        const value = this.decycle(this.json);
        this.segments =
            typeof value === 'object' && value !== null
                ? Object.keys(value).map((key) => this.parseKeyValue(key, (value as Record<string, unknown>)[key]))
                : [this.parseKeyValue(`(${typeof value})`, value)];
    }

    public isExpandable(segment: Segment): boolean {
        return segment.type === 'object' || segment.type === 'array';
    }

    public toggle(segment: Segment): void {
        if (this.isExpandable(segment)) {
            segment.expanded = !segment.expanded;
        }
    }

    private parseKeyValue(key: string, value: unknown): Segment {
        const segment: Segment = {
            key,
            value,
            type: 'unknown',
            description: `${value}`,
            expanded: this.expanded,
        };

        switch (typeof value) {
            case 'number':
                segment.type = 'number';
                break;
            case 'boolean':
                segment.type = 'boolean';
                break;
            case 'function':
                segment.type = 'function';
                break;
            case 'string':
                segment.type = 'string';
                segment.description = `"${value}"`;
                break;
            case 'undefined':
                segment.type = 'undefined';
                segment.description = 'undefined';
                break;
            case 'object':
                if (value === null) {
                    segment.type = 'null';
                    segment.description = 'null';
                } else if (Array.isArray(value)) {
                    segment.type = 'array';
                    segment.description = `Array[${value.length}] ${JSON.stringify(value)}`;
                } else if (value instanceof Date) {
                    segment.type = 'date';
                } else {
                    segment.type = 'object';
                    segment.description = `Object ${JSON.stringify(value)}`;
                }
                break;
        }

        return segment;
    }

    private decycle(root: unknown): unknown {
        const seen = new WeakMap<object, string>();

        const derez = (value: unknown, path: string): unknown => {
            if (
                typeof value !== 'object' ||
                value === null ||
                value instanceof Boolean ||
                value instanceof Date ||
                value instanceof Number ||
                value instanceof RegExp ||
                value instanceof String
            ) {
                return value;
            }

            const previousPath = seen.get(value);
            if (previousPath !== undefined) {
                return { $ref: previousPath };
            }
            seen.set(value, path);

            if (Array.isArray(value)) {
                return value.map((element, index) => derez(element, `${path}[${index}]`));
            }

            return Object.fromEntries(
                Object.entries(value).map(([name, nested]) => [name, derez(nested, `${path}[${JSON.stringify(name)}]`)])
            );
        };

        return derez(root, '$');
    }
}
