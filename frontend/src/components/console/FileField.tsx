import { useEffect, useRef, useState } from 'react';

interface FileFieldProps {
  id: string;
  label: string;
  accept: string;
  hint?: string;
  multiple?: boolean;
  /** Главное поле формы: крупная зона, файл можно перетащить. */
  drop?: boolean;
  files: File[];
  onChange: (files: File[]) => void;
}

/** Поле файла. Родной input[type=file] показывает системную надпись «Файл не выбран», которую
 *  нельзя ни перевести, ни набрать своим шрифтом: сам input прозрачен и растянут на всё поле,
 *  видимой его частью работают подпись и имя выбранного файла. */
export function FileField({
  id,
  label,
  accept,
  hint,
  multiple = false,
  drop = false,
  files,
  onChange,
}: FileFieldProps) {
  const input = useRef<HTMLInputElement>(null);
  const [over, setOver] = useState(false);

  // Выбор улицы сбрасывает файл: поле обязано показать пустоту, а не прежний выбор браузера.
  useEffect(() => {
    if (!files.length && input.current) input.current.value = '';
  }, [files]);

  const chosen = files.length > 1 ? `файлов: ${files.length}` : (files[0]?.name ?? 'не выбран');
  return (
    <div className="field">
      <span className="field-title" id={`${id}-label`}>
        {label}
      </span>
      {/* Зона перетаскивания - тот же прозрачный input на всё поле: браузер сам принимает
          брошенный на него файл, подсветка только показывает, что бросать можно. */}
      <div
        className={drop ? 'filefield drop' : 'filefield'}
        data-over={over || undefined}
        onDragEnter={() => {
          setOver(true);
        }}
        onDragLeave={() => {
          setOver(false);
        }}
        onDrop={() => {
          setOver(false);
        }}
      >
        <input
          ref={input}
          type="file"
          id={id}
          accept={accept}
          multiple={multiple}
          aria-labelledby={`${id}-label`}
          aria-describedby={hint ? `${id}-hint` : undefined}
          onChange={(event) => {
            onChange([...(event.target.files ?? [])]);
          }}
        />
        {drop && !files.length ? (
          <span className="drop-hint" aria-hidden="true">
            Перетащите чертёж сюда
          </span>
        ) : null}
        <span className="pick" aria-hidden="true">
          {drop ? 'Выбрать файл' : 'Выбрать'}
        </span>
        <span className="chosen" data-chosen={files.length ? '1' : '0'}>
          {chosen}
        </span>
      </div>
      {hint ? (
        <p className="hint" id={`${id}-hint`}>
          {hint}
        </p>
      ) : null}
    </div>
  );
}
