/* Редактор промпта фото нейросетью: собранный сервисом текст, который можно поправить.
 *
 * Пока текст не тронут, сервис собирает промпт сам под каждый кадр: сезон, час, точка съёмки,
 * виды в кадре. Правка делает промпт своим: он уходит со всеми следующими фото как есть, виды
 * кадра в него уже не подставляются. «Вернуть автоматический» отменяет правку. */

import type { PromptOut } from '../../api/types';

export interface PromptDraft {
  text: string;
  negative: string;
}

export interface PromptEditorProps {
  auto: PromptOut | undefined;
  draft: PromptDraft | null;
  onDraft: (draft: PromptDraft | null) => void;
}

export function PromptEditor({ auto, draft, onDraft }: PromptEditorProps) {
  const text = draft?.text ?? auto?.text ?? '';
  const negative = draft?.negative ?? auto?.negative ?? '';
  const edit = (patch: Partial<PromptDraft>) => {
    onDraft({ text, negative, ...patch });
  };
  return (
    <details className="prompt-editor">
      <summary>
        Промпт{' '}
        <span className="prompt-state">
          {draft ? 'свой, со всеми следующими фото' : 'автоматический'}
        </span>
      </summary>
      <label className="prompt-field">
        <span>Что нарисовать</span>
        <textarea
          rows={8}
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
          rows={3}
          maxLength={4000}
          value={negative}
          onChange={(e) => {
            edit({ negative: e.target.value });
          }}
        />
      </label>
      {draft ? (
        <div className="prompt-foot">
          <p className="hint">Виды из кадра в свой промпт не подставляются.</p>
          <button
            type="button"
            className="ghost small"
            onClick={() => {
              onDraft(null);
            }}
          >
            вернуть автоматический
          </button>
        </div>
      ) : (
        <p className="hint">Сервис подставит сезон, час, точку съёмки и виды из кадра.</p>
      )}
    </details>
  );
}
