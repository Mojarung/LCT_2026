import { useEffect, useRef } from 'react';

interface FileFieldProps {
  id: string;
  label: string;
  accept: string;
  hint?: string;
  multiple?: boolean;
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
  files,
  onChange,
}: FileFieldProps) {
  const input = useRef<HTMLInputElement>(null);

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
      <div className="filefield">
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
        <span className="pick" aria-hidden="true">
          Выбрать
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
