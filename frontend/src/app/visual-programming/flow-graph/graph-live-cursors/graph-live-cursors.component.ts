import { ChangeDetectionStrategy, Component, computed, input } from "@angular/core";
import { EditorInfo } from "src/app/features/flows/services/graph-collaboration.ws.service";
import { getAvatarColor } from "../../core/helpers/avatar-colors";

export interface CursorState {
    x: number;
    y: number;
    editor: EditorInfo;
    fading: boolean;
}


@Component({
    selector: 'app-graph-live-cursors',
    standalone: true,
    template: `
        @for (cursor of cursorsArray(); track cursor.userId) {
            <div class="remote-cursor"
                [class.fading]="cursor.state.fading"
                [style.transform]="'translate(' + cursor.state.x + 'px, ' + cursor.state.y + 'px)'"
            >
                <svg width="14" height="18" viewBox="0 0 14 18" xmlns="http://www.w3.org/2000/svg">
                    <path d="M1 1 L1 15 L4 12 L7 18 L9 17 L6 11 L10 11 Z"
                          [attr.fill]="getColor(cursor.userId)"
                          stroke="white"
                          stroke-width="0.8"
                          stroke-linejoin="round"
                    />
                </svg>
                <span class="cursor-label" [style.background-color]="getColor(cursor.userId)">
                    {{ displayName(cursor.state.editor) }}
                </span>
            </div>
        }
    `,
    styles: [`
        :host {
            position: absolute;
            top: 0;
            left: 0;
            pointer-events: none;
            overflow: visible;
        }
        .remote-cursor {
            position: absolute;
            top: 0;
            left: 0;
            pointer-events: none;
            display: flex;
            align-items: flex-start;
            gap: 4px;
            white-space: nowrap;
            opacity: 1;
            transition: opacity 0.3s ease;
        }
        .remote-cursor.fading {
            opacity: 0;
        }
        .cursor-label {
            margin-top: 16px;
            padding: 2px 6px;
            border-radius: 3px;
            font-size: 11px;
            color: white;
            line-height: 1.4;
            max-width: 120px;
            overflow: hidden;
            text-overflow: ellipsis;
        }  
    `],
    changeDetection: ChangeDetectionStrategy.OnPush,
})

export class GraphLiveCursorsComponent {
    readonly cursors = input<Map<number, CursorState>>(new Map());

    protected readonly cursorsArray = computed(() => 
        Array.from(this.cursors().entries()).map(([userId, state]) => ({userId, state}))
    );

    protected getColor(userId: number): string {
        return getAvatarColor(userId);
    }

    protected displayName(editor: EditorInfo): string {
        return editor.display_name ?? `User ${editor.user_id}`
    }
}