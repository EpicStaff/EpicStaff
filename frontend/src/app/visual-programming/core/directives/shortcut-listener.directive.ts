import {
  Directive,
  EventEmitter,
  OnDestroy,
  OnInit,
  Output,
  NgZone,
} from '@angular/core';
import { fromEvent, Subscription } from 'rxjs';
import { filter } from 'rxjs/operators';

@Directive({ selector: '[appShortcutListener]', standalone: true })
export class ShortcutListenerDirective implements OnInit, OnDestroy {
  @Output() copy = new EventEmitter<void>();
  @Output() paste = new EventEmitter<void>();
  @Output() delete = new EventEmitter<void>();
  @Output() undo = new EventEmitter<void>();
  @Output() redo = new EventEmitter<void>();
  @Output() refresh = new EventEmitter<void>();
  @Output() save = new EventEmitter<void>();
  @Output() escape = new EventEmitter<void>();

  private sub!: Subscription;
  private readonly allowedKeys = new Set([
    'c',
    'с',
    'v',
    'м',
    'z',
    'я',
    'y',
    'н',
    'r',
    'к',
    's',
    'ы',
    'delete',
    'backspace',
    'escape',
  ]);

  constructor(private ngZone: NgZone) {}

  ngOnInit() {
    this.ngZone.runOutsideAngular(() => {
      this.sub = fromEvent<KeyboardEvent>(window, 'keydown')
        .pipe(
          filter((evt: KeyboardEvent) => {
            const key: string = evt.key.toLowerCase();
            const mod: boolean = evt.ctrlKey || evt.metaKey;

            // 1) only keep delete/backspace/escape OR keys with ctrl/meta
            if (
              !(
                this.allowedKeys.has(key) &&
                (key === 'delete' ||
                  key === 'backspace' ||
                  key === 'escape' ||
                  mod)
              )
            ) {
              return false;
            }

            // 2) bail if user is typing in a form or contenteditable, except for Escape
            const el = evt.target as HTMLElement;
            if (
              key !== 'escape' &&
              el.matches('input,textarea,select,[contenteditable="true"]')
            ) {
              return false;
            }

            return true;
          })
        )
        .subscribe((evt) => {
          this.ngZone.run(() => this.handleKeydown(evt));
        });
    });
  }

  private handleKeydown(event: KeyboardEvent) {
    const key = event.key.toLowerCase();
    if (key === 'delete' || key === 'backspace') {
      event.preventDefault();
      event.stopPropagation();
      this.delete.emit();
      return;
    }
    if (key === 'escape') {
      event.preventDefault();
      event.stopPropagation();
      this.escape.emit();
      return;
    }
    const mod = event.ctrlKey || event.metaKey;
    if (!mod) {
      return;
    }

    switch (key) {
      case 'c':
      case 'с':
        event.preventDefault();
        event.stopPropagation();
        this.copy.emit();
        break;
      case 'v':
      case 'м':
        event.preventDefault();
        event.stopPropagation();
        this.paste.emit();
        break;
      case 'z':
      case 'я':
        event.preventDefault();
        event.stopPropagation();
        event.shiftKey ? this.redo.emit() : this.undo.emit();
        break;
      case 'y':
      case 'н':
        event.preventDefault();
        event.stopPropagation();
        this.redo.emit();
        break;
      case 'r':
      case 'к':
        event.preventDefault();
        event.stopPropagation();
        this.refresh.emit();
        break;
      case 's':
      case 'ы':
        event.preventDefault();
        event.stopPropagation();
        this.save.emit();
        break;
    }
  }

  ngOnDestroy() {
    this.sub.unsubscribe();
  }
}
