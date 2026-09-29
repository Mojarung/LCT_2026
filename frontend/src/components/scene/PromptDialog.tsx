/* Промпт фото нейросетью: собранный сервисом текст, который можно поправить, в отдельном окне.
 *
 * Пока текст не тронут, сервис собирает промпт сам под каждый кадр: сезон, час, точка съёмки,
 * виды в кадре. Правка делает промпт своим: он уходит со всеми следующими фото как есть, виды
 * кадра в него уже не подставляются. «Вернуть автоматический» отменяет правку.
 *
 * Модальный <dialog>: поля крупные, а в узкой панели снимков остаётся одна кнопка «промпт». */

import { useEffect, useRef } from 'react';

import type { PromptOut } from '../../api/types';

export interface PromptDraft {
  text: string;
  negative: string;
}

export interface PromptDialogProps {
  auto: PromptOut | undefined;
  draft: PromptDraft | null;
  onDraft: (draft: PromptDraft | null) => void;
  onClose: () => void;
}

export function PromptDialog({ auto, draft, onDraft, onClose }: PromptDialogProps) {
  const dialog = useRef<HTMLDialogElement>(null);
  const close = useRef(onClose);
  useEffect(() => {
    close.current = onClose;
  });
  useEffect(() => {
    const box = dialog.current;
    if (!box) return;
    if (typeof box.showModal === 'function' && !box.open) box.showModal();
    const cancel = (event: Event) => {
      event.preventDefault();
      close.current();
    };
    box.addEventListener('cancel', cancel);
    return () => {
      box.removeEventListener('cancel', cancel);
      if (box.open) box.close();
    };
  }, []);

  const text = draft?.text ?? auto?.text ?? '';
  const negative = draft?.negative ?? auto?.negative ?? '';
  const edit = (patch: Partial<PromptDraft>) => {
    onDraft({ text, negative, ...patch });
  };
  return (
    <dialog ref={dialog} className="prompt-dialog" aria-labelledby="prompt-title">
      <header className="prompt-head">
        <h2 id="prompt-title">Промпт фото ИИ</h2>
        <span className="prompt-state" data-custom={draft ? 'true' : undefined}>
          {draft ? 'свой' : 'автоматический'}
        </span>
      </header>
      <p className="hint">
        {draft
          ? 'Свой промпт уходит со всеми следующими фото как есть: виды из кадра в него не подставляются.'
          : 'Сервис подставит сезон, час, точку съёмки и виды из кадра. Поправьте текст, и он станет своим.'}
      </p>
      <label className="prompt-field">
        <span>Что нарисовать</span>
        <textarea
          rows={12}
          maxLength={4000}
          value={text}
          onChange={(e) => {
            edit({ text: e.target.value });
          }}
        />
      </label>
      <label className="prompt-field">
        <span>Чего не рисовать</span>
        <textarea
          rows={4}
          maxLength={4000}
          value={negative}
          onChange={(e) => {
            edit({ negative: e.target.value });
          }}
        />
      </label>
      <footer className="prompt-foot">
        {draft ? (
          <button
            type="button"
            className="ghost small"
            onClick={() => {
              onDraft(null);
            }}
          >
            вернуть автоматический
          </button>
        ) : null}
        <button type="button" className="primary small" onClick={onClose}>
          готово
        </button>
      </footer>
    </dialog>
  );
}
