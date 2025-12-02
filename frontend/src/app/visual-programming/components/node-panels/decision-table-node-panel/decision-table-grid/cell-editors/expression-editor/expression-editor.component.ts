import {
    Component,
    ViewChild,
    ElementRef,
    AfterViewInit,
    ChangeDetectionStrategy,
    inject,
    signal,
    computed,
    OnDestroy,
    ViewContainerRef,
    effect
} from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { ICellEditorAngularComp } from 'ag-grid-angular';
import { ICellEditorParams } from 'ag-grid-community';
import { AutocompleteOverlayComponent, AutocompleteItem } from './autocomplete-overlay/autocomplete-overlay.component';
import { EditorToolbarComponent } from './editor-toolbar/editor-toolbar.component';
import { FlowService } from '../../../../../../services/flow.service';
import { Overlay, OverlayModule, OverlayRef } from '@angular/cdk/overlay';
import { ComponentPortal } from '@angular/cdk/portal';

@Component({
    selector: 'app-expression-editor',
    standalone: true,
    imports: [CommonModule, FormsModule, AutocompleteOverlayComponent, EditorToolbarComponent, OverlayModule],
    templateUrl: './expression-editor.component.html',
    styleUrls: ['./expression-editor.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class ExpressionEditorComponent
    implements ICellEditorAngularComp, AfterViewInit, OnDestroy
{
    @ViewChild('input', { read: ElementRef })
    public input!: ElementRef<HTMLTextAreaElement>;
    @ViewChild('backdrop', { read: ElementRef })
    public backdrop!: ElementRef<HTMLDivElement>;
    
    private flowService = inject(FlowService);
    private overlay = inject(Overlay);
    private viewContainerRef = inject(ViewContainerRef);

    public value: string = '';
    private params!: ICellEditorParams;

    // Autocomplete state
    public showAutocomplete = signal<boolean>(false);
    public filterText = signal<string>('');
    public currentPath = signal<string[]>([]);
    
    private overlayRef: OverlayRef | null = null;
    private componentPortal: ComponentPortal<AutocompleteOverlayComponent> | null = null;
    private autocompleteInstance: AutocompleteOverlayComponent | null = null;

    public autocompleteItems = computed<AutocompleteItem[]>(() => {
        const startNodeState = this.flowService.startNodeInitialState();
        if (!startNodeState) return [];
        
        let current: any = startNodeState;
        for (const key of this.currentPath()) {
            if (current && typeof current === 'object') {
                current = current[key];
            } else {
                return [];
            }
        }

        if (!current || typeof current !== 'object') return [];

        return Object.keys(current).map(key => ({
            key,
            path: [...this.currentPath(), key].join('.'),
            type: (typeof current[key] === 'object' && current[key] !== null) ? 'group' : 'value',
            value: current[key]
        }));
    });
    
    private cursorPosition: number = 0;

    constructor() {
        // Effect to manage overlay visibility and data
        effect(() => {
            const show = this.showAutocomplete();
            if (show) {
                this.openOverlay();
            } else {
                this.closeOverlay();
            }
        });

        // Effect to update overlay inputs when data changes
        effect(() => {
            if (this.autocompleteInstance) {
                this.autocompleteInstance.updateData(
                    this.autocompleteItems(),
                    this.currentPath(),
                    this.filterText()
                );
            }
        });
    }

    ngOnDestroy(): void {
        this.closeOverlay();
    }

    private openOverlay(): void {
        if (this.overlayRef?.hasAttached()) {
            return; // Already open
        }

        // We want to position the overlay near the cursor, or specifically near the '@' that triggered it.
        // Since we can't easily get the exact pixel coordinates of the cursor in a textarea without a library,
        // and we want a native-like feel, we can use a workaround:
        // Create a temporary span element that mirrors the text up to the cursor, measure its position, 
        // and position the overlay there.
        // OR simpler: position relative to the textarea but offset? No, that's static.
        
        // Get cursor coordinates relative to textarea
        const cursorCoords = this.getCursorCoordinates();
        
        // Flexible position strategy with fallbacks for all directions
        const positionStrategy = this.overlay.position()
            .flexibleConnectedTo(this.input)
            .withPositions([
                // Below cursor (preferred)
                {
                    originX: 'start',
                    originY: 'top',
                    overlayX: 'start',
                    overlayY: 'top',
                    offsetX: cursorCoords.left,
                    offsetY: cursorCoords.top + 10
                },
                // Above cursor (if no space below)
                {
                    originX: 'start',
                    originY: 'top',
                    overlayX: 'start',
                    overlayY: 'bottom',
                    offsetX: cursorCoords.left,
                    offsetY: cursorCoords.top - 10
                },
                // Below, aligned right (if no space on left)
                {
                    originX: 'end',
                    originY: 'top',
                    overlayX: 'end',
                    overlayY: 'top',
                    offsetX: cursorCoords.left - 250, // Overlay width ~280px
                    offsetY: cursorCoords.top + 10
                },
                // Above, aligned right
                {
                    originX: 'end',
                    originY: 'top',
                    overlayX: 'end',
                    overlayY: 'bottom',
                    offsetX: cursorCoords.left - 250,
                    offsetY: cursorCoords.top - 10
                }
            ])
            .withPush(true)
            .withViewportMargin(8)
            .withFlexibleDimensions(false);

        this.overlayRef = this.overlay.create({
            positionStrategy,
            scrollStrategy: this.overlay.scrollStrategies.reposition(),
            hasBackdrop: false // No backdrop - nothing closes the overlay except explicit actions
        });

        this.componentPortal = new ComponentPortal(AutocompleteOverlayComponent, this.viewContainerRef);
        const componentRef = this.overlayRef.attach(this.componentPortal);
        this.autocompleteInstance = componentRef.instance;
        
        // Prevent overlay interactions from stealing focus from input
        const overlayElement = this.overlayRef.overlayElement;
        overlayElement.addEventListener('mousedown', (e) => {
            e.preventDefault();
            e.stopPropagation();
            // Keep focus on input
            setTimeout(() => this.input.nativeElement.focus());
        });

        // Subscribe to outputs manually
        this.autocompleteInstance.itemSelected.subscribe((item: AutocompleteItem) => this.onItemSelect(item));
        this.autocompleteInstance.navigateUp.subscribe(() => this.onNavigateUp());
        this.autocompleteInstance.navigateDown.subscribe((item: AutocompleteItem) => this.onNavigateDown(item));
        this.autocompleteInstance.navigateToPath.subscribe((index: number) => this.onNavigateToPath(index));
        
        // Initial data set
        this.autocompleteInstance.updateData(
            this.autocompleteItems(),
            this.currentPath(),
            this.filterText()
        );
    }
    
    private getCursorCoordinates(): { top: number, left: number } {
        const textarea = this.input.nativeElement;
        
        const textBeforeCursor = this.value.substring(0, this.cursorPosition);
        const lastAtIndex = textBeforeCursor.lastIndexOf('@');
        
        // Position relative to the triggering '@'
        const textToMeasure = textBeforeCursor.substring(0, lastAtIndex); 
        
        const div = document.createElement('div');
        const style = getComputedStyle(textarea);
        
        // Copy essential styles
        div.style.fontFamily = style.fontFamily;
        div.style.fontSize = style.fontSize;
        div.style.lineHeight = style.lineHeight;
        div.style.fontWeight = style.fontWeight;
        div.style.whiteSpace = 'pre-wrap';
        div.style.wordBreak = 'break-word';
        div.style.width = style.width;
        div.style.padding = style.padding;
        div.style.boxSizing = style.boxSizing;
        div.style.position = 'fixed'; // Fixed to avoid scroll interfering with measurement
        div.style.visibility = 'hidden';
        div.style.top = textarea.getBoundingClientRect().top + 'px';
        div.style.left = textarea.getBoundingClientRect().left + 'px';
        
        div.textContent = textToMeasure;
        const span = document.createElement('span');
        span.textContent = '@';
        div.appendChild(span);
        
        document.body.appendChild(div);
        
        const spanRect = span.getBoundingClientRect();
        const textareaRect = textarea.getBoundingClientRect();
        
        // Calculate relative offset from top-left of textarea
        // Also account for scroll position of textarea
        const top = (spanRect.bottom - textareaRect.top) - textarea.scrollTop;
        const left = (spanRect.left - textareaRect.left) - textarea.scrollLeft;
        
        document.body.removeChild(div);
        
        return { top, left };
    }

    private closeOverlay(): void {
        if (this.overlayRef) {
            this.overlayRef.dispose();
            this.overlayRef = null;
            this.autocompleteInstance = null;
        }
    }

    agInit(params: ICellEditorParams): void {
        this.params = params;
        this.value = params.value || '';
        this.updateHighlighting();
    }

    getValue(): any {
        return this.value;
    }

    isPopup(): boolean {
        return true;
    }

    ngAfterViewInit(): void {
        setTimeout(() => {
            this.input.nativeElement.focus();
            this.updateHighlighting();
        });
    }

    onInput(event: Event): void {
        const textarea = event.target as HTMLTextAreaElement;
        this.value = textarea.value;
        this.cursorPosition = textarea.selectionStart;

        this.updateHighlighting();
        this.checkForAutocompleteTrigger();
    }

    onScroll(): void {
        if (this.backdrop && this.input) {
            this.backdrop.nativeElement.scrollTop = this.input.nativeElement.scrollTop;
            this.backdrop.nativeElement.scrollLeft = this.input.nativeElement.scrollLeft;
        }
    }
    
    onBlur(event: FocusEvent): void {
        // If autocomplete is showing, prevent blur from causing issues
        // Refocus the input to keep editor open
        if (this.showAutocomplete()) {
            event.preventDefault();
            setTimeout(() => {
                this.input.nativeElement.focus();
            });
        }
    }

    private updateHighlighting(): void {
        if (!this.backdrop) return;

        const text = this.value || '';
        // Escape HTML
        let escaped = text
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#039;');

        // Highlight variables (state.x.y)
        escaped = escaped.replace(/(@?state(?:\.[\w$]+)+)\b/g, '<span class="variable">$1</span>');

        // Highlight AND/OR (case insensitive)
        escaped = escaped.replace(/(\b(?:AND|OR|and|or)\b)/g, '<span class="keyword">$1</span>');

        // Handle trailing newline
        if (escaped.endsWith('\n')) {
            escaped += '<br>';
        }

        this.backdrop.nativeElement.innerHTML = escaped;
    }

    private checkForAutocompleteTrigger(): void {
        const textBeforeCursor = this.value.substring(0, this.cursorPosition);
        const lastAtIndex = textBeforeCursor.lastIndexOf('@');

        if (lastAtIndex !== -1) {
            const textAfterAt = textBeforeCursor.substring(lastAtIndex + 1);
            if (!/\s/.test(textAfterAt)) {
                this.showAutocomplete.set(true);
                this.filterText.set(textAfterAt);
                return;
            }
        }
        
        this.showAutocomplete.set(false);
    }

    onKeyDown(event: KeyboardEvent): void {
        if (this.showAutocomplete() && this.autocompleteInstance) {
            if (event.key === 'ArrowDown') {
                event.preventDefault();
                this.autocompleteInstance.navigateNext();
                return;
            } else if (event.key === 'ArrowUp') {
                event.preventDefault();
                this.autocompleteInstance.navigatePrev();
                return;
            } else if (event.key === 'Enter' || event.key === 'Tab') {
                event.preventDefault();
                event.stopPropagation(); // Stop propagation to prevent grid editor from closing
                this.autocompleteInstance.selectActive();
                return;
            } else if (event.key === 'ArrowRight') {
                const active = this.autocompleteInstance.activeItem();
                if (active && active.type === 'group') {
                    event.preventDefault();
                    this.onNavigateDown(active);
                }
            } else if (event.key === 'ArrowLeft') {
                if (this.currentPath().length > 0) {
                    event.preventDefault();
                    this.onNavigateUp();
                }
            } else if (event.key === 'Escape') {
                // Don't close - do nothing on Escape
                event.preventDefault();
                event.stopPropagation();
                return;
            }
        }

        if (event.key === 'Enter' && !event.shiftKey) {
            event.preventDefault();
            this.params.stopEditing();
        } else if (event.key === 'Enter' && event.shiftKey) {
            event.stopPropagation();
        } else if (event.key === 'Tab') {
            event.preventDefault();
            if (event.shiftKey) {
                this.params.api.tabToPreviousCell();
            } else {
                this.params.api.tabToNextCell();
            }
        }
    }

    public insertToken(token: string): void {
        if (token === '@') {
            this.insertTextAtCursor('@');
        } else {
            this.insertTextAtCursor(` ${token} `);
        }
    }

    private insertTextAtCursor(text: string): void {
        const textarea = this.input.nativeElement;
        textarea.focus();

        const success = document.execCommand('insertText', false, text);

        if (!success) {
            const start = textarea.selectionStart;
            const end = textarea.selectionEnd;
            const value = textarea.value;
            
            this.value = value.substring(0, start) + text + value.substring(end);
            
            setTimeout(() => {
                const newPos = start + text.length;
                textarea.setSelectionRange(newPos, newPos);
                this.cursorPosition = newPos;
                this.updateHighlighting();
            });
        } else {
            this.value = textarea.value;
            this.cursorPosition = textarea.selectionStart;
            this.updateHighlighting();
        }
    }

    onItemSelect(item: AutocompleteItem): void {
        const textBeforeCursor = this.value.substring(0, this.cursorPosition);
        const lastAtIndex = textBeforeCursor.lastIndexOf('@');
        
        if (lastAtIndex !== -1) {
            const textarea = this.input.nativeElement;
            textarea.focus();
            textarea.setSelectionRange(lastAtIndex + 1, this.cursorPosition);
            
            const variablePath = `state.${item.path}`;
            
            const success = document.execCommand('insertText', false, variablePath);
            
            if (!success) {
                const prefix = this.value.substring(0, lastAtIndex + 1);
                const suffix = this.value.substring(this.cursorPosition);
                this.value = `${prefix}${variablePath}${suffix}`;
                
                setTimeout(() => {
                    const newCursorPos = lastAtIndex + 1 + variablePath.length;
                    textarea.setSelectionRange(newCursorPos, newCursorPos);
                    this.updateHighlighting();
                });
            } else {
                this.value = textarea.value;
                this.cursorPosition = textarea.selectionStart;
                this.updateHighlighting();
            }

            this.showAutocomplete.set(false);
            this.currentPath.set([]); // Reset path
            
            textarea.focus();
        }
    }

    onNavigateDown(item: AutocompleteItem): void {
        const textBeforeCursor = this.value.substring(0, this.cursorPosition);
        const lastAtIndex = textBeforeCursor.lastIndexOf('@');

        if (lastAtIndex !== -1) {
            this.currentPath.update(path => [...path, item.key]);
            
            const prefix = this.value.substring(0, lastAtIndex);
            const suffix = this.value.substring(this.cursorPosition);
            this.value = `${prefix}@${suffix}`;
            
            this.filterText.set('');
            
            // Directly update the overlay with new data
            if (this.autocompleteInstance) {
                this.autocompleteInstance.updateData(
                    this.autocompleteItems(),
                    this.currentPath(),
                    this.filterText()
                );
            }
            
            setTimeout(() => {
                this.input.nativeElement.focus();
                const newCursorPos = lastAtIndex + 1;
                this.input.nativeElement.setSelectionRange(newCursorPos, newCursorPos);
                this.cursorPosition = newCursorPos;
            });
        }
    }

    onNavigateUp(): void {
        this.currentPath.update(path => {
            if (path.length === 0) return path;
            return path.slice(0, -1);
        });
        
        // Update the overlay with new data
        if (this.autocompleteInstance) {
            this.autocompleteInstance.updateData(
                this.autocompleteItems(),
                this.currentPath(),
                this.filterText()
            );
        }
    }
    
    onNavigateToPath(index: number): void {
        // index -1 means root, otherwise slice path to that index + 1
        if (index === -1) {
            this.currentPath.set([]);
        } else {
            this.currentPath.update(path => path.slice(0, index + 1));
        }
        
        // Update the overlay with new data
        if (this.autocompleteInstance) {
            this.autocompleteInstance.updateData(
                this.autocompleteItems(),
                this.currentPath(),
                this.filterText()
            );
        }
    }
}
